"""Shared UART execution for production and robot debugging.

P values are protocol positions, not degrees; movement commands have no reply.
"""
from __future__ import annotations
import copy
import glob
from pathlib import Path
import threading
import time
from collections import deque
from .hardware_lock import hardware_operation_lock
from .protocol import (JOINT_IDS, PUMP_ID, BAUD_RATE, PUMP_ON, PUMP_OFF, PUMP_RESET,
                       move_command, suggested_port as suggested_port, configured_port)
from .parameters import DEFAULTS as DEFAULTS, POSES, LABELS, SETTINGS, validate, load_params, _write_params

API_VERSION = "servo-dashboard-ascii-uart-v1"

class Cancelled(Exception):
    pass


class Runtime:
    def __init__(self, demo=False, settings_path=SETTINGS, pump_enabled=True):
        self.demo = demo
        self.settings_path = Path(settings_path)
        self.params = load_params(self.settings_path)
        self.pump_enabled = bool(pump_enabled)
        self.serial = None
        self.device = configured_port()
        self.fault = None
        self.busy = False
        self.pump_position = None
        self.message = "演示模式：不会发送硬件指令" if demo else "请选择串口并连接"
        self.logs = deque(maxlen=120)
        self.lock = threading.RLock()
        self.operation = threading.Lock()
        self.cancel = threading.Event()
        self.worker = None

    def snapshot(self):
        with self.lock:
            ports = sorted(set(p for pattern in ("/dev/serial*", "/dev/ttyAMA*", "/dev/ttyS*", "/dev/ttyUSB*", "/dev/ttyACM*", "/dev/cu.*") for p in glob.glob(pattern)))
            return {"ok": True, "api_version": API_VERSION, "demo": self.demo,
                    "connected": self.demo or self.serial is not None,
                    "device": self.device, "ports": ports, "busy": self.busy,
                    "fault": self.fault, "message": self.message, "pump_position": self.pump_position,
                    "pump_available": self.pump_enabled, "arm_position_verification": False,
                    "params": copy.deepcopy(self.params), "logs": list(self.logs), "labels": LABELS}

    def save(self, params):
        clean = validate(params)
        with self.lock, hardware_operation_lock(str(self.settings_path) + ".lock"):
            _write_params(self.settings_path, clean)
            self.params = clean

    def connect(self, device=None):
        if device in {None, "", "auto"}:
            device = configured_port()
        if not isinstance(device, str) or not device.startswith("/dev/") or len(device) > 256:
            raise ValueError("请输入 /dev/ 开头的串口设备路径")
        with self.lock:
            if self.busy:
                raise ValueError("动作运行中不能切换串口")
            self._close()
            self.device = device
            if not self.demo:
                try:
                    import serial
                    # Exclusive ownership prevents a second process using this same UART.
                    self.serial = serial.Serial(device, BAUD_RATE, bytesize=8, parity="N", stopbits=1,
                                                timeout=0.1, write_timeout=0.5, exclusive=True,
                                                xonxoff=False, rtscts=False, dsrdtr=False)
                except Exception as exc:
                    self.fault = f"串口连接失败：{exc}"
                    self.message = self.fault
                    raise ValueError(self.fault) from exc
            self.fault = None
            self.pump_position = None
            self.message = "演示模式已就绪" if self.demo else "串口已打开（尚未验证舵机响应）"

    def _close(self):
        serial_port, self.serial = self.serial, None
        if serial_port is not None:
            serial_port.close()

    def send(self, data, stopping=False):
        with self.lock:
            if self.cancel.is_set() and not stopping:
                raise Cancelled()
            if not self.demo:
                if self.serial is None:
                    raise RuntimeError("串口未连接，请连接后重试")
                try:
                    if self.serial.write(data) != len(data):
                        raise IOError("串口数据未完整写出")
                    deadline = time.monotonic() + 0.75
                    while self.serial.out_waiting:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("串口发送排空超时")
                        time.sleep(0.001)
                except Exception:
                    self.pump_position = None
                    self._close()
                    raise
            tag = "[PUMP]" if data.startswith(f"#{PUMP_ID:03d}".encode()) else "[ARM]"
            self.logs.append(time.strftime("%H:%M:%S ") + tag + (" DEMO " if self.demo else " TX ") + data.decode("ascii"))
            print(self.logs[-1], flush=True)

    def wait(self, milliseconds):
        if self.cancel.wait(milliseconds / 1000):
            raise Cancelled()

    def joints(self, values, duration):
        if len(values) != len(JOINT_IDS):
            raise ValueError("需要五个关节位置")
        commands = [move_command(sid, pos, duration) for sid, pos in zip(JOINT_IDS, values)]
        for command in commands:
            self.send(command)

    def pump(self, position, duration):
        if not self.pump_enabled:
            return
        self.send(move_command(PUMP_ID, position, duration))
        with self.lock:
            self.pump_position = position

    def _begin(self, action, params, target, pose, save=False):
        clean = validate(params)
        if action not in {"move", "sequence", "pump_on", "pump_off", "pump_reset", "recover"}:
            raise ValueError("未知动作")
        if action.startswith("pump_") and not self.pump_enabled:
            raise ValueError("气泵控制已通过 DISABLE_PUMP 禁用")
        if action == "move" and pose not in POSES:
            raise ValueError("未知姿态")
        if target not in {"left", "right"}:
            raise ValueError("未知方向")
        if not self.operation.acquire(blocking=False):
            raise ValueError("动作正在执行，请等待完成或点击停止")
        try:
            with self.lock:
                if not self.demo and self.serial is None:
                    raise ValueError("请先连接串口")
                if self.fault:
                    raise ValueError("发生串口故障，请重新连接")
                if save:
                    self.save(clean)
                self.cancel.clear()
                self.busy = True
                self.message = "执行中…"
            return clean
        except BaseException:
            self.operation.release()
            raise

    def start(self, action, params, target="right", pose=None):
        clean = self._begin(action, params, target, pose, save=True)
        self.worker = threading.Thread(target=self._worker, args=(action, clean, target, pose), daemon=True)
        try:
            self.worker.start()
        except BaseException:
            with self.lock:
                self.busy = False
            self.operation.release()
            raise

    def _worker(self, action, params, target, pose):
        try:
            self._perform(action, params, target, pose)
        except Exception:
            pass  # _perform records the fault; asynchronous caller observes snapshot.

    def execute(self, action, params, target="right", pose=None):
        """Synchronous production entry; exceptions propagate to caller / exit code."""
        clean = self._begin(action, params, target, pose)
        self._perform(action, clean, target, pose)

    def _perform(self, action, params, target, pose):
        try:
            with hardware_operation_lock():
                if action == "move":
                    self.joints(params["poses"][pose], params["manual_ms"])
                    self.wait(params["manual_ms"])
                elif action == "recover":
                    self.pump(PUMP_OFF, params["move_ms"][3])
                    self.wait(params["wait_ms"][3])
                    self.joints(params["poses"]["reset"], params["move_ms"][4])
                    self.wait(params["wait_ms"][4])
                elif action.startswith("pump_"):
                    self.pump({"pump_on": PUMP_ON, "pump_off": PUMP_OFF, "pump_reset": PUMP_RESET}[action], params["manual_ms"])
                    self.wait(params["manual_ms"])
                else:
                    names = ("pickup", target + "_transfer", target + "_drop", target + "_drop", "reset")
                    pumps = (PUMP_ON, PUMP_ON, PUMP_ON, PUMP_OFF, PUMP_RESET)
                    for phase, (name, pump) in enumerate(zip(names, pumps)):
                        with self.lock:
                            self.message = f"Phase {phase} · {LABELS[name]}"
                        print(f"[ARM] STEP phase={phase} pose={name} T={params['move_ms'][phase]} wait={params['wait_ms'][phase]}", flush=True)
                        self.joints(params["poses"][name], params["move_ms"][phase])
                        self.pump(pump, params["move_ms"][phase])
                        self.wait(params["wait_ms"][phase])
                with self.lock:
                    self.message = "指令发送及设定等待已完成（无位置回读）"
        except Cancelled:
            with self.lock:
                self.message = "流程已取消；停止指令状态见日志，气泵保持原命令"
            raise
        except BaseException as exc:
            with self.lock:
                self.fault = f"动作中止：{type(exc).__name__}: {exc}"
                self.message = self.fault + "；未自动复位"
            raise
        finally:
            with self.lock:
                self.busy = False
            self.operation.release()

    def stop(self):
        with self.lock:
            self.cancel.set()
            try:
                for sid in JOINT_IDS:
                    self.send(f"#{sid:03d}PDST!".encode("ascii"), stopping=True)
                self.message = "已发送关节停止指令；气泵保持原命令（停止未回读确认）"
            except Exception as exc:
                self.fault = f"停止指令未确认发送：{exc}"
                self.message = self.fault
                raise ValueError(self.fault) from exc

    def close(self):
        if self.busy:
            try:
                self.stop()
            except ValueError:
                pass
        if self.worker and self.worker is not threading.current_thread():
            self.worker.join(timeout=2)
        with self.lock:
            self._close()
