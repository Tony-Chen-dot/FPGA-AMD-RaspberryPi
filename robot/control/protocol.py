"""ZL ASCII UART frame format, device IDs and port selection."""
from __future__ import annotations
import math
import os
from pathlib import Path

# 硬件参数：对应 Verilog servo_id=0..5；005 按源码当作吸取控制通道。
JOINT_IDS = (0, 1, 2, 3, 4)
PUMP_ID = 5
BAUD_RATE = 115200
PUMP_ON = 2500
PUMP_OFF = 500
PUMP_RESET = 1500  # 忠实保留 FPGA phase4；不假定这个值等同于关闭。
POSITION_MIN, POSITION_MAX = 500, 2500
def integer(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("参数必须是数值")
    if not math.isfinite(value) or int(value) != value or not low <= value <= high:
        raise ValueError(f"参数必须为 {low}～{high} 的整数")
    return int(value)


def move_command(servo_id, position, duration):
    return f"#{integer(servo_id, 0, 254):03d}P{integer(position, 500, 2500):04d}T{integer(duration, 0, 9999):04d}!".encode("ascii")


def suggested_port():
    model = Path("/proc/device-tree/model")
    if model.exists() and "Raspberry Pi 5" in model.read_text():
        return "/dev/ttyAMA0"
    return "/dev/serial0"


def configured_port():
    value = os.environ.get("ARM_SERIAL_PORT", "auto").strip()
    return suggested_port() if value in {"", "auto"} else value


