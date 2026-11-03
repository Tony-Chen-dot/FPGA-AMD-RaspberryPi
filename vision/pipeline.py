from __future__ import annotations


import argparse
import base64
import json
import os
import signal
import shutil
import sys
import subprocess
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.paths import VISION_RUNTIME_DIR
from common.production_lines import configured_line_id, migrate_legacy_runtime
from vision.workers.tasks import TriggerTask, ActionTask, create_trigger_identity
from vision.capture.frame_reader import LatestFrameReader
from vision.workers.fifo import BoundedFifoWorker

import cv2

from vision.transport.inference_client import DashboardTransport
from vision.detection.circles import CircleDetection, EnhancementConfig, FrameEnhancer, annotate_frame, detect_circles
from vision.capture.hikrobot import HikrobotCameraCapture, HikrobotCameraError, enumerate_hikrobot_devices

TRIGGER_OVERLAY_DURATION_MS = 1500


class CircleCameraApp:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.project_dir = Path(args.project_dir).resolve()
        self.artifacts_dir = self.project_dir / "artifacts"
        self.logs_dir = self.project_dir / "logs"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.preview_path = self.artifacts_dir / "live_annotated.jpg"
        self.runtime_log_path = self.logs_dir / "runtime_status.log"
        self.transport = DashboardTransport(
            artifacts_dir=self.artifacts_dir,
            ingest_endpoint_url=args.dashboard_ingest_url,
            live_frame_endpoint_url=args.dashboard_live_frame_url,
            request_timeout=args.request_timeout,
            live_frame_request_timeout=args.live_frame_request_timeout,
            live_frame_width=args.live_frame_width,
            live_frame_height=args.live_frame_height,
            live_frame_jpeg_quality=args.live_frame_jpeg_quality,
            live_frame_scale=args.live_frame_scale,
            crop_min_area_ratio=args.crop_min_area_ratio,
            board_predict_url=args.board_predict_url,
            board_file_field=args.board_file_field,
            board_score_thresh=args.board_score_thresh,
            board_request_timeout=args.board_request_timeout,
            board_input_size=args.board_input_size,
            board_jpeg_quality=args.board_jpeg_quality,
            board_send_raw=args.board_send_raw,
        )
        self.running = True
        self.last_status_time = 0.0
        self.last_trigger_time = 0.0
        self.last_preview_write = 0.0
        self.last_live_push = 0.0
        self.frame_counter = 0
        self.next_action_id = 1
        self.camera_backend_name = "unknown"
        self.trigger_worker = BoundedFifoWorker(
            name="circle-trigger",
            capacity=args.trigger_queue_capacity,
            handler=self._process_trigger_task,
            error_handler=self._worker_error,
        )
        self.action_worker = BoundedFifoWorker(
            name="circle-action",
            capacity=args.action_queue_capacity,
            handler=self._process_action_task,
            error_handler=self._worker_error,
            capacity_includes_active=True,
        )
        self.detection_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="circle-detect")
        self.detection_future: Future | None = None
        self.detection_preview_frame = None
        self.last_detection_submit_time = 0.0
        self.detection_lock = threading.Lock()
        self.latest_circles: list[CircleDetection] = []
        self.latest_target: CircleDetection | None = None
        self.latest_detection_frame = None
        self.latest_detection_gray = None
        self.event_lock = threading.Lock()
        self.trigger_snapshot_data_url: str | None = None
        self.trigger_snapshot_expires_at_ms = 0
        self.sent_status_expires_at_ms = 0
        self.frame_enhancer = FrameEnhancer(
            EnhancementConfig(
                clahe_clip_limit=args.enhance_clahe_clip_limit,
                clahe_tile_grid_size=args.enhance_clahe_grid_size,
                contrast_gain=args.enhance_contrast_gain,
                brightness_beta=args.enhance_brightness_beta,
                detail_gain=args.enhance_detail_gain,
                sharpen_sigma=args.enhance_sharpen_sigma,
                sharpen_amount=args.enhance_sharpen_amount,
                median_denoise_kernel=args.enhance_median_denoise_kernel,
                gaussian_denoise_sigma=args.enhance_gaussian_denoise_sigma,
                bilateral_denoise_diameter=args.enhance_bilateral_denoise_diameter,
                bilateral_denoise_sigma_color=args.enhance_bilateral_denoise_sigma_color,
                bilateral_denoise_sigma_space=args.enhance_bilateral_denoise_sigma_space,
            )
        )

    @property
    def effective_center_threshold_px(self) -> int:
        return max(1, self.args.center_threshold_px * 4)

    @property
    def effective_center_threshold_y_px(self) -> int:
        return max(1, int(round(self.effective_center_threshold_px * 2)))

    def stop(self, *_args) -> None:
        self.running = False

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}"
        print(line, flush=True)
        with self.runtime_log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _worker_error(self, worker_name: str, exc: Exception) -> None:
        self.log(f"后台任务异常 | worker={worker_name} | {type(exc).__name__}: {exc}")

    def select_target(self, circles: list[CircleDetection]) -> CircleDetection | None:
        return circles[0] if circles else None

    def should_trigger(self, target: CircleDetection | None, frame_shape: tuple[int, int, int]) -> bool:
        if target is None:
            return False
        center_x = frame_shape[1] // 2
        center_y = frame_shape[0] // 2
        dx = target.x - center_x
        dy = target.y - center_y
        ellipse_radius_x = max(1, self.effective_center_threshold_px)
        ellipse_radius_y = max(1, self.effective_center_threshold_y_px)
        normalized = (
            (dx / ellipse_radius_x) ** 2
            + (dy / ellipse_radius_y) ** 2
        )
        if normalized > 1.0:
            return False
        if (time.time() - self.last_trigger_time) < self.args.continuous_capture_cool_time:
            return False
        return True

    def build_live_payload(self, circles: list[CircleDetection], target: CircleDetection | None) -> dict:
        with self.event_lock:
            now_ms = int(time.time() * 1000)
            trigger_overlay = {
                "image_data": self.trigger_snapshot_data_url,
                "expires_at_ms": self.trigger_snapshot_expires_at_ms,
                "sent_until_ms": self.sent_status_expires_at_ms,
            }
            if self.trigger_snapshot_expires_at_ms <= now_ms and self.sent_status_expires_at_ms <= now_ms:
                self.trigger_snapshot_data_url = None
                trigger_overlay = None

        return {
            "timestamp": datetime.now().isoformat(),
            "line_id": configured_line_id(),
            "board_name": self.args.board_name,
            "model_name": self.args.model_name,
            "comm_state": "connected",
            "stream_state": "live",
            "circle_count": len(circles),
            "shape_mode": "circle_detection_center_ellipse_v2",
            "selected_circle": asdict(target) if target else None,
            "all_circles": [asdict(circle) for circle in circles],
            "trigger_overlay": trigger_overlay,
            "trigger_queue": {
                "depth": self.trigger_worker.depth,
                "capacity": self.trigger_worker.capacity,
                "warning": self.trigger_worker.depth >= max(1, self.trigger_worker.capacity - 2),
            },
            "frame_id": f"live-{self.frame_counter}",
        }

    def save_trigger_bundle(
        self,
        frame,
        gray,
        circles: list[CircleDetection],
        target: CircleDetection,
    ) -> bool:
        trigger_monotonic = time.monotonic()
        trigger_epoch_ms = int(time.time() * 1000)
        timestamp, artifact_token, frame_id = create_trigger_identity()
        task = TriggerTask(
            timestamp=timestamp,
            artifact_token=artifact_token,
            frame_id=frame_id,
            frame=annotate_frame(frame, circles, self.effective_center_threshold_px).copy(),
            gray=gray.copy(),
            circles_payload=[asdict(circle) for circle in circles],
            target_payload=asdict(target),
            trigger_monotonic=trigger_monotonic,
            trigger_epoch_ms=trigger_epoch_ms,
            enqueued_monotonic=time.monotonic(),
        )
        submitted = self.trigger_worker.submit(task)

        if not submitted:
            self.log(
                f"推理队列过载 | frame_id={frame_id} | depth={self.trigger_worker.depth}/"
                f"{self.trigger_worker.capacity} | 本片未覆盖其他样品，已明确拒绝"
            )
            return False
        depth = self.trigger_worker.depth
        if depth >= max(1, self.trigger_worker.capacity - 2):
            self.log(f"推理队列告警 | frame_id={frame_id} | depth={depth}/{self.trigger_worker.capacity}")
        else:
            self.log(f"触发入队 | frame_id={frame_id} | depth={depth}/{self.trigger_worker.capacity}")
        return True

    def _process_trigger_task(self, task: TriggerTask) -> None:
        queue_wait_ms = (time.monotonic() - task.enqueued_monotonic) * 1000.0
        self._process_trigger_bundle(
            task.timestamp,
            task.artifact_token,
            task.frame_id,
            task.frame,
            task.gray,
            task.circles_payload,
            task.target_payload,
            task.trigger_monotonic,
            task.trigger_epoch_ms,
            queue_wait_ms,
        )

    def _process_trigger_bundle(
        self,
        timestamp: str,
        artifact_token: str,
        frame_id: str,
        frame,
        gray,
        circles_payload: list[dict],
        target_payload: dict,
        trigger_started_at: float,
        trigger_epoch_ms: int,
        queue_wait_ms: float,
    ) -> None:
        metadata = {
            "timestamp": timestamp,
            "frame_id": frame_id,
            "trigger_epoch_ms": trigger_epoch_ms,
            "line_id": configured_line_id(),
            "board_name": self.args.board_name,
            "model_name": self.args.model_name,
            "result": "NG",
            "defect_count": 1,
            "frame_size": {"width": int(frame.shape[1]), "height": int(frame.shape[0])},
            "frame": {"width": int(frame.shape[1]), "height": int(frame.shape[0])},
            "circle_count": len(circles_payload),
            "shape_mode": "circle_detection_center_ellipse_v2",
            "center_threshold_px": self.effective_center_threshold_px,
            "selected_circle": target_payload,
            "all_circles": circles_payload,
            "gpio_pin": None,
            "pipeline_timing": {"queue_wait_ms": round(queue_wait_ms, 2)},
            "notes": "Target circle entered the center ellipse trigger zone; the square crop is resized to the fixed board input size.",
        }
        result = self.transport.export_gray_payload(gray, metadata)
        total_ms = (time.monotonic() - trigger_started_at) * 1000.0
        result.timing_ms["trigger_to_dashboard_ms"] = round(total_ms, 2)
        artifact_paths = self._save_final_artifacts(artifact_token, result)
        if result.ok:
            with self.event_lock:
                self.sent_status_expires_at_ms = int(time.time() * 1000) + TRIGGER_OVERLAY_DURATION_MS
            action_result = self._extract_result_label(result.response_payload)
            if action_result:
                action_id = self.next_action_id
                self.next_action_id += 1
                action_task = ActionTask(
                    action_id,
                    frame_id,
                    action_result,
                    trigger_started_at,
                    time.monotonic(),
                )
                action_tag = f"A{action_id:03d}"
                def log_action_in(total: int, waiting: int) -> None:
                    self.log(
                        f"[QUEUE] IN {action_tag} {action_result} | total={total}/"
                        f"{self.action_worker.capacity} | wait={waiting} | frame_id={frame_id}"
                    )

                if not self.action_worker.submit(action_task, accepted_handler=log_action_in):
                    self.log(
                        f"[QUEUE] DROP {action_tag} {action_result} | full={self.action_worker.in_flight}/"
                        f"{self.action_worker.capacity} | frame_id={frame_id} | 已入库但动作拒绝"
                    )
            else:
                self.log(f"未从返回 JSON 中找到 OK/NG，跳过机械臂动作 | response={result.response_payload}")
        timing_json = json.dumps(result.timing_ms, ensure_ascii=False, separators=(",", ":"))
        self.log(
            f"链路完成 | frame_id={frame_id} | ok={result.ok} | artifacts={artifact_paths or 'disabled'} | "
            f"timing_ms={timing_json} | {result.detail}"
        )

    def _save_final_artifacts(self, timestamp: str, result) -> str:
        if self.args.artifact_mode != "final" or not result.artifact_image_bytes:
            return ""
        image_path = self.artifacts_dir / f"result_{timestamp}.jpg"
        json_path = self.artifacts_dir / f"result_{timestamp}.json"
        image_path.write_bytes(result.artifact_image_bytes)
        payload = dict(result.artifact_payload or {})
        payload["pipeline_timing"] = dict(result.timing_ms)
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return f"{image_path.name},{json_path.name}"

    def _process_action_task(self, task: ActionTask) -> None:
        action_tag = f"A{task.action_id:03d}"
        started = time.monotonic()
        queue_wait_ms = (started - task.enqueued_monotonic) * 1000.0
        deadline_lag_ms = max(
            0.0,
            (started - (task.trigger_monotonic + float(self.args.action_delay_seconds))) * 1000.0,
        )
        self.log(
            f"[QUEUE] OUT {action_tag} {task.result_label} | total={self.action_worker.in_flight}/"
            f"{self.action_worker.capacity} | wait={self.action_worker.depth} | queue_wait_ms={queue_wait_ms:.2f} | "
            f"lag={deadline_lag_ms:.2f}ms | frame_id={task.frame_id}"
        )
        succeeded = self._run_pose_action_for_result(
            task.result_label,
            task.trigger_monotonic,
            task.frame_id,
            action_tag,
        )
        cost_seconds = time.monotonic() - started
        event = "DONE" if succeeded else "FAIL"
        remaining = max(0, self.action_worker.in_flight - 1)
        self.log(
            f"[QUEUE] {event} {action_tag} {task.result_label} | total={remaining}/"
            f"{self.action_worker.capacity} | wait={self.action_worker.depth} | cost={cost_seconds:.2f}s | "
            f"frame_id={task.frame_id}"
        )

    def _extract_result_label(self, payload) -> str | None:
        if isinstance(payload, dict):
            for key in ("result", "status", "label", "class", "outcome"):
                value = payload.get(key)
                if isinstance(value, str):
                    normalized = value.strip().upper()
                    if normalized in {"OK", "NG"}:
                        return normalized
            for value in payload.values():
                nested = self._extract_result_label(value)
                if nested:
                    return nested
        if isinstance(payload, list):
            for value in payload:
                nested = self._extract_result_label(value)
                if nested:
                    return nested
        return None

    def _run_pose_action_for_result(
        self,
        result_label: str,
        trigger_started_at: float,
        frame_id: str = "unknown",
        action_tag: str = "A---",
    ) -> bool:
        if self.args.disable_arm_action:
            self.log(f"机械臂动作已禁用 | result={result_label}")
            return True

        direction_mode = int(self.args.action_direction_mode)
        if direction_mode == 0:
            target_direction = "left" if result_label == "NG" else "right"
        else:
            target_direction = "right" if result_label == "NG" else "left"

        elapsed = time.monotonic() - trigger_started_at
        wait_seconds = max(0.0, float(self.args.action_delay_seconds) - elapsed)
        if wait_seconds > 0:
            self.log(f"等待机械臂动作计时 t0={self.args.action_delay_seconds:.3f}s | 剩余={wait_seconds:.3f}s")
            time.sleep(wait_seconds)
        deadline_lag_ms = max(
            0.0,
            (time.monotonic() - (trigger_started_at + float(self.args.action_delay_seconds))) * 1000.0,
        )
        self.log(f"机械臂定时到达 | frame_id={frame_id} | action_deadline_lag_ms={deadline_lag_ms:.2f}")

        raspberry_root = PROJECT_ROOT
        runner_path = Path(self.args.pose_runner_path).expanduser()
        if not runner_path.is_absolute():
            runner_path = raspberry_root / runner_path
        params_path = Path(self.args.action_params_path).expanduser()
        if not params_path.is_absolute():
            params_path = raspberry_root / params_path

        mode = f"forward-{target_direction}"
        timeout_seconds = self._action_timeout_seconds(params_path, target_direction)
        command = [
            self.args.action_python,
            str(runner_path),
            "--mode",
            mode,
            "--params",
            str(params_path),
        ]
        if self.args.action_live:
            command.append("--live")

        self.log(
            f"[ARM] {action_tag} move={mode} start | result={result_label} | direction_mode={direction_mode} | "
            f"mode={mode} | live={self.args.action_live} | timings=dashboard_params | "
            f"timeout={timeout_seconds:.2f}s"
        )
        try:
            completed = subprocess.run(
                command,
                cwd=str(raspberry_root),
                check=False,
                timeout=timeout_seconds,
            )
            if completed.returncode != 0:
                raise subprocess.CalledProcessError(completed.returncode, command)
            self.log("机械臂动作完成")
            self.log(f"[ARM] {action_tag} move={mode} complete")
            return True
        except Exception as exc:
            self.log(f"[ARM] {action_tag} move={mode} failed | {type(exc).__name__}: {exc}")
            self._run_pose_recovery(raspberry_root, runner_path, params_path)
            return False

    def _action_timeout_seconds(self, params_path: Path, target_direction: str) -> float:
        configured = max(5.0, float(self.args.action_timeout_seconds))
        try:
            params = json.loads(params_path.read_text(encoding="utf-8"))
            # 众灵 UART 使用五阶段等待表；T 已由舵机内部执行，不重复累加。
            # 其余触发、方向映射、队列、失败恢复流程保持原样。
            if isinstance(params.get("move_ms"), list):
                waits = params["wait_ms"]
                moves = params["move_ms"]
                if len(waits) != 5 or len(moves) != 5:
                    raise ValueError("Expected five UART phases")
                expected = sum(max(0, int(value)) for value in waits) / 1000.0
                # 30 条 8N1 / 15 字节报文约 0.04s，另留进程启动和串口写入余量。
                return max(configured, expected + 5.0)
            return configured
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return configured

    def _run_pose_recovery(self, raspberry_root: Path, runner_path: Path, params_path: Path) -> None:
        command = [
            self.args.action_python,
            str(runner_path),
            "--recover",
            "--params",
            str(params_path),
        ]
        if self.args.action_live:
            command.append("--live")

        self.log("执行机械臂安全恢复 | 关泵并返回 reset")
        recovery_timeout = max(8.0, min(15.0, float(self.args.action_timeout_seconds)))
        try:
            recovery_params = json.loads(params_path.read_text(encoding="utf-8"))
            if isinstance(recovery_params.get("move_ms"), list):
                waits = recovery_params["wait_ms"]
                if len(waits) == 5:
                    recovery_timeout = max(recovery_timeout, (int(waits[3]) + int(waits[4])) / 1000.0 + 5.0)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass
        try:
            completed = subprocess.run(
                command,
                cwd=str(raspberry_root),
                check=True,
                timeout=recovery_timeout,
            )
            self.log("机械臂安全恢复完成")
        except Exception as recovery_exc:
            self.log(
                f"机械臂安全恢复失败 | {type(recovery_exc).__name__}: {recovery_exc} | "
                "请立即检查气泵状态，并手动执行 robot/actions/run_sequence.py --recover --live"
            )

    def write_preview(self, annotated) -> None:
        now = time.time()
        if now - self.last_preview_write < self.args.preview_save_interval_seconds:
            return
        cv2.imwrite(str(self.preview_path), annotated)
        self.last_preview_write = now

    def push_live_frame(self, annotated, circles: list[CircleDetection], target: CircleDetection | None) -> None:
        now = time.time()
        if now - self.last_live_push < (1.0 / max(1, self.args.live_push_fps)):
            return
        result = self.transport.send_live_frame(annotated, self.build_live_payload(circles, target))
        live_error = self.transport.consume_live_frame_error()
        if live_error and now - self.last_status_time >= self.args.status_interval_seconds:
            self.log(live_error)
        if not result.ok and now - self.last_status_time >= self.args.status_interval_seconds:
            self.log(result.detail)
        self.last_live_push = now

    def print_status(self, circles: list[CircleDetection], target: CircleDetection | None) -> None:
        now = time.time()
        if now - self.last_status_time < self.args.status_interval_seconds:
            return
        if circles:
            circle_text = " | ".join(
                f"#{index + 1}(x={circle.x},y={circle.y},r={circle.radius},d={circle.distance_to_center:.1f})"
                for index, circle in enumerate(circles[:4])
            )
        else:
            circle_text = "未检测到圆"
        target_text = (
            f"目标圆: x={target.x}, y={target.y}, d={target.distance_to_center:.1f}"
            if target
            else "目标圆: 无"
        )
        self.log(
            f"运行中 | frame={self.frame_counter} | backend={self.camera_backend_name} | "
            f"circles={len(circles)} | center_threshold_px={self.effective_center_threshold_px} | "
            f"center_threshold_y_px={self.effective_center_threshold_y_px} | "
            f"{target_text} | {circle_text}"
        )
        self.last_status_time = now

    def run(self) -> int:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

        os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_GSTREAMER", "0")
        cap = self._open_camera()
        if cap is None:
            self.log(
                f"无法打开摄像头 | camera_source={self.args.camera_source} | "
                f"camera_index={self.args.camera_index} | hikrobot_index={self.args.hikrobot_camera_index} | "
                f"hikrobot_serial={self.args.hikrobot_camera_serial or '--'}"
            )
            return 1

        self._configure_camera(cap)
        frame_reader = LatestFrameReader(cap)
        frame_reader.start()

        self.log(
            f"圆检测采集已启动 | camera_source={self.args.camera_source} | camera_index={self.args.camera_index} | "
            f"hikrobot_index={self.args.hikrobot_camera_index} | fps={self.args.fps} | "
            f"camera_backend={self.camera_backend_name} | live_push_fps={self.args.live_push_fps} | "
            f"detection_fps={self.args.detection_fps} | detection_width={self.args.detection_width} | "
            f"live_frame_bounds={self.args.live_frame_width}x{self.args.live_frame_height} | "
            f"live_frame_scale={self.args.live_frame_scale} | jpeg_quality={self.args.live_frame_jpeg_quality} | "
            f"ingest_url={self.args.dashboard_ingest_url} | live_frame_url={self.args.dashboard_live_frame_url}"
        )

        last_sequence = 0
        try:
            while self.running:
                last_sequence, frame, preview_frame = frame_reader.get_latest_with_preview(last_sequence, timeout_seconds=0.45)
                if frame is None:
                    continue

                self.frame_counter += 1
                self._poll_detection_result()
                self._maybe_submit_detection(frame, preview_frame)
                circles, target = self._current_detection_state()

                # Keep the live video path light: raw camera frames go out first,
                # detection and enhancement run in the background.
                self.write_preview(frame)
                self.push_live_frame(preview_frame, circles, target)

                if self.args.show_window:
                    preview = annotate_frame(frame, circles, self.effective_center_threshold_px)
                    cv2.imshow("circle-monitor", preview)
                    if (cv2.waitKey(1) & 0xFF) == ord("q"):
                        self.log("收到 q，准备退出。")
                        break
        finally:
            frame_reader.stop()
            cap.release()
            cv2.destroyAllWindows()
            self.transport.close()
            self.trigger_worker.close()
            self.action_worker.close()
            self.detection_executor.shutdown(wait=True, cancel_futures=True)
            self.log("圆检测采集已停止。")

        return 0

    def _open_camera(self):
        if self.args.camera_source in {"auto", "hikrobot"}:
            sdk_root = Path(self.args.hikrobot_sdk_path).expanduser()
            if sdk_root.exists():
                try:
                    camera_index = self.args.hikrobot_camera_index
                    if camera_index is None:
                        camera_index = self.args.camera_index
                    cap = HikrobotCameraCapture(
                        sdk_root=sdk_root,
                        camera_index=camera_index,
                        serial_number=self.args.hikrobot_camera_serial,
                        width=self.args.width,
                        height=self.args.height,
                        fps=self.args.fps,
                        frame_timeout_ms=self.args.hikrobot_frame_timeout_ms,
                    )
                    self.camera_backend_name = f"{cap.backend_name}({cap.device_description})"
                    self.log(
                        f"海康相机打开成功 | sdk={sdk_root} | "
                        f"device={cap.device_description} | "
                        f"capture={cap.capture_width}x{cap.capture_height} -> output={cap.width}x{cap.height}"
                    )
                    return cap
                except HikrobotCameraError as exc:
                    self.log(f"海康相机打开失败 | {exc}")
                    if self.args.camera_source == "hikrobot":
                        return None
            elif self.args.camera_source == "hikrobot":
                self.log(f"未找到海康 MVS SDK 目录: {sdk_root}")
                return None

        if self.args.camera_source == "hikrobot":
            return None

        attempts = [
            ("V4L2", lambda: cv2.VideoCapture(self.args.camera_index, cv2.CAP_V4L2)),
            ("default", lambda: cv2.VideoCapture(self.args.camera_index)),
        ]
        for backend_name, opener in attempts:
            cap = opener()
            if cap is not None and cap.isOpened():
                self.camera_backend_name = backend_name
                self.log(f"摄像头打开成功 | device=/dev/video{self.args.camera_index} | backend={backend_name}")
                return cap
            if cap is not None:
                cap.release()
            self.log(f"摄像头打开失败 | device=/dev/video{self.args.camera_index} | backend={backend_name}")
        return None

    def _configure_camera(self, cap) -> None:
        if self.camera_backend_name.startswith("HIKROBOT-MVS"):
            self.log("当前使用海康 MVS 取流，已跳过 V4L2 专用摄像头参数设置。")
            return
        if self.args.camera_fourcc:
            requested_fourcc = self.args.camera_fourcc[:4].ljust(4)
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*requested_fourcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.args.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.args.height)
        cap.set(cv2.CAP_PROP_FPS, self.args.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._configure_camera_controls()

    def _configure_camera_controls(self) -> None:
        controls = {
            "brightness": self.args.camera_brightness,
            "contrast": self.args.camera_contrast,
            "gamma": self.args.camera_gamma,
            "gain": self.args.camera_gain,
            "sharpness": self.args.camera_sharpness,
        }
        selected_controls = {name: value for name, value in controls.items() if value is not None}
        if not selected_controls:
            return

        v4l2_ctl = shutil.which("v4l2-ctl")
        if not v4l2_ctl:
            self.log("未找到 v4l2-ctl，跳过摄像头硬件亮度/对比度设置。")
            return

        device = f"/dev/video{self.args.camera_index}"
        for name, value in selected_controls.items():
            command = [v4l2_ctl, "-d", device, "--set-ctrl", f"{name}={int(value)}"]
            try:
                subprocess.run(command, check=True, capture_output=True, text=True, timeout=1.5)
            except Exception as exc:
                self.log(f"摄像头参数设置失败 | {name}={value} | {exc}")
        self.log(
            "摄像头参数已设置 | "
            + " | ".join(f"{name}={value}" for name, value in selected_controls.items())
        )

    def _safe_remove(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass

    def _run_detection(self, frame):
        return detect_circles(
            frame,
            dp=self.args.hough_dp,
            min_dist=self.args.hough_min_dist,
            param1=self.args.hough_param1,
            param2=self.args.hough_param2,
            min_radius=self.args.min_radius,
            max_radius=self.args.max_radius,
            min_circularity=self.args.min_circularity,
            min_edge_support=self.args.min_edge_support,
            center_reject_margin_px=self.args.center_reject_margin_px,
            max_candidates=self.args.max_candidates,
            min_contour_area_ratio=self.args.min_contour_area_ratio,
            max_contour_area_ratio=self.args.max_contour_area_ratio,
            min_fill_ratio=self.args.min_fill_ratio,
            max_radial_error_ratio=self.args.max_radial_error_ratio,
            detection_width=self.args.detection_width,
            enhancer=self.frame_enhancer,
        )

    def _maybe_submit_detection(self, frame, preview_frame=None) -> None:
        now = time.time()
        if self.detection_future is not None and not self.detection_future.done():
            return
        if now - self.last_detection_submit_time < (1.0 / max(1, self.args.detection_fps)):
            return
        self.last_detection_submit_time = now
        # Retain the unpadded view from this exact detection sample, not a
        # newer live frame when the background detection eventually finishes.
        self.detection_preview_frame = preview_frame
        self.detection_future = self.detection_executor.submit(self._run_detection, frame.copy())

    def _poll_detection_result(self) -> None:
        if self.detection_future is None or not self.detection_future.done():
            return
        future = self.detection_future
        preview_frame = self.detection_preview_frame
        self.detection_preview_frame = None
        self.detection_future = None
        try:
            circles, gray, enhanced_frame = future.result()
        except Exception as exc:
            self.log(f"后台圆检测失败 | {exc}")
            return

        target = self.select_target(circles)
        with self.detection_lock:
            self.latest_circles = circles
            self.latest_target = target
            self.latest_detection_frame = enhanced_frame
            self.latest_detection_gray = gray

        if self.should_trigger(target, enhanced_frame.shape):
            if self.save_trigger_bundle(enhanced_frame, gray, circles, target):
                self.last_trigger_time = time.time()
                self._arm_trigger_overlay(preview_frame if preview_frame is not None else enhanced_frame)

        self.print_status(circles, target)

    def _current_detection_state(self) -> tuple[list[CircleDetection], CircleDetection | None]:
        with self.detection_lock:
            return list(self.latest_circles), self.latest_target

    def _arm_trigger_overlay(self, frame) -> None:
        snapshot = self._encode_trigger_snapshot(frame)
        if snapshot is None:
            return
        with self.event_lock:
            now_ms = int(time.time() * 1000)
            self.trigger_snapshot_data_url = snapshot
            self.trigger_snapshot_expires_at_ms = now_ms + TRIGGER_OVERLAY_DURATION_MS
            self.sent_status_expires_at_ms = 0

    def _encode_trigger_snapshot(self, frame) -> str | None:
        height, width = frame.shape[:2]
        max_width = 480
        if width > max_width:
            scale = max_width / width
            frame = cv2.resize(
                frame,
                (max(1, int(width * scale)), max(1, int(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            return None
        payload = base64.b64encode(encoded.tobytes()).decode("ascii")
        return f"data:image/jpeg;base64,{payload}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Raspberry Pi camera relay with circle detection")
    parser.add_argument("--project-dir", default=str(VISION_RUNTIME_DIR))
    parser.add_argument("--camera-source", choices=("auto", "v4l2", "hikrobot"), default="auto")
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--camera-fourcc", default="MJPG")
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--camera-brightness", type=int, default=None)
    parser.add_argument("--camera-contrast", type=int, default=None)
    parser.add_argument("--camera-gamma", type=int, default=None)
    parser.add_argument("--camera-gain", type=int, default=None)
    parser.add_argument("--camera-sharpness", type=int, default=None)
    parser.add_argument("--hikrobot-sdk-path", default="/opt/MVS")
    parser.add_argument("--hikrobot-camera-index", type=int, default=None)
    parser.add_argument("--hikrobot-camera-serial", default="")
    parser.add_argument("--hikrobot-frame-timeout-ms", type=int, default=200)
    parser.add_argument("--list-hikrobot-cameras", action="store_true", default=False)
    parser.add_argument("--live-push-fps", type=int, default=24)
    parser.add_argument("--detection-fps", type=float, default=8.0)
    parser.add_argument("--detection-width", type=int, default=384)
    parser.add_argument("--center-threshold-px", type=int, default=14)
    parser.add_argument(
        "--continuous-capture-cool-time",
        "--trigger-cooldown-seconds",
        dest="continuous_capture_cool_time",
        type=float,
        default=2.0,
        help="Seconds to wait after a successful trigger before another capture (default: 2.0)",
    )
    parser.add_argument("--status-interval-seconds", type=float, default=1.0)
    parser.add_argument("--preview-save-interval-seconds", type=float, default=1.2)
    parser.add_argument("--hough-dp", type=float, default=1.15)
    parser.add_argument("--hough-min-dist", type=float, default=140.0)
    parser.add_argument("--hough-param1", type=float, default=90.0)
    parser.add_argument("--hough-param2", type=float, default=22.0)
    parser.add_argument("--min-radius", type=int, default=120)
    parser.add_argument("--max-radius", type=int, default=640)
    parser.add_argument("--min-circularity", type=float, default=0.0)
    parser.add_argument("--min-edge-support", type=float, default=0.22)
    parser.add_argument("--min-contour-area-ratio", type=float, default=0.003)
    parser.add_argument("--max-contour-area-ratio", type=float, default=0.75)
    parser.add_argument("--min-fill-ratio", type=float, default=0.22)
    parser.add_argument("--max-radial-error-ratio", type=float, default=0.42)
    parser.add_argument("--crop-min-area-ratio", type=float, default=0.05)
    parser.add_argument("--center-reject-margin-px", type=int, default=8)
    parser.add_argument("--max-candidates", type=int, default=6)
    parser.add_argument("--dashboard-ingest-url", default="http://127.0.0.1:8000/api/device/ingest")
    parser.add_argument("--dashboard-live-frame-url", default="http://127.0.0.1:8000/api/device/live_frame")
    parser.add_argument("--board-predict-url", default="")
    parser.add_argument("--board-file-field", default="image_file")
    parser.add_argument("--board-score-thresh", type=float, default=0.2)
    parser.add_argument("--board-request-timeout", type=float, default=5.0)
    parser.add_argument("--board-input-size", type=int, default=300)
    parser.add_argument("--board-jpeg-quality", type=int, default=85)
    parser.add_argument(
        "--board-send-raw",
        action="store_true",
        default=False,
        help="向板端发送无压缩原始 RGB888 字节流（默认发送 JPEG；开启前需板端支持原始流接收）",
    )
    parser.add_argument("--trigger-queue-capacity", type=int, default=8)
    parser.add_argument("--artifact-mode", choices=("final", "none"), default="final")
    parser.add_argument("--request-timeout", type=float, default=3.0)
    parser.add_argument("--live-frame-request-timeout", type=float, default=0.25)
    parser.add_argument("--live-frame-width", type=int, default=1536)
    parser.add_argument("--live-frame-height", type=int, default=1024)
    parser.add_argument("--live-frame-scale", type=float, default=1.0,
                        help="Preview width/height multiplier, greater than 0 and at most 1")
    parser.add_argument("--live-frame-jpeg-quality", type=int, default=85)
    parser.add_argument("--action-delay-seconds", type=float, default=10.0)
    parser.add_argument(
        "--action-queue-capacity",
        type=int,
        default=3,
        help="Maximum arm actions in flight, including the active action",
    )
    parser.add_argument("--action-direction-mode", type=int, choices=(0, 1), default=0)
    parser.add_argument("--action-hold-seconds", type=float, default=0.2)
    parser.add_argument("--action-pump-before-seconds", type=float, default=0.1)
    parser.add_argument("--action-pump-after-seconds", type=float, default=0.7)
    parser.add_argument("--action-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--action-python", default="/usr/bin/python3")
    parser.add_argument("--action-params-path", default="runtime/robot/servo_params.json")
    parser.add_argument("--pose-runner-path", default="robot/actions/run_sequence.py")
    parser.add_argument("--action-live", action="store_true", default=True)
    parser.add_argument("--no-action-live", action="store_false", dest="action_live")
    parser.add_argument("--disable-arm-action", action="store_true", default=False)
    parser.add_argument("--enhance-clahe-clip-limit", type=float, default=2.4)
    parser.add_argument("--enhance-clahe-grid-size", type=int, default=8)
    parser.add_argument("--enhance-contrast-gain", type=float, default=1.15)
    parser.add_argument("--enhance-brightness-beta", type=float, default=-2.0)
    parser.add_argument("--enhance-detail-gain", type=float, default=0.0)
    parser.add_argument("--enhance-sharpen-sigma", type=float, default=1.0)
    parser.add_argument("--enhance-sharpen-amount", type=float, default=0.55)
    parser.add_argument("--enhance-median-denoise-kernel", type=int, default=3)
    parser.add_argument("--enhance-gaussian-denoise-sigma", type=float, default=0.0)
    parser.add_argument("--enhance-bilateral-denoise-diameter", type=int, default=3)
    parser.add_argument("--enhance-bilateral-denoise-sigma-color", type=float, default=16.0)
    parser.add_argument("--enhance-bilateral-denoise-sigma-space", type=float, default=16.0)
    parser.add_argument("--board-name", default="Zynq 多产线推理加速器")
    parser.add_argument("--model-name", default="Zynq 缺陷检测模型")
    parser.add_argument("--show-window", action="store_true", default=False)
    parser.add_argument("--no-show-window", action="store_false", dest="show_window")
    return parser


def main() -> int:
    try:
        cv2.setNumThreads(max(1, int(os.environ.get("OPENCV_THREADS", "2"))))
    except (TypeError, ValueError):
        cv2.setNumThreads(2)
    args = build_parser().parse_args()
    if args.list_hikrobot_cameras:
        try:
            devices = enumerate_hikrobot_devices(args.hikrobot_sdk_path)
        except HikrobotCameraError as exc:
            print(f"列出海康相机失败: {exc}", flush=True)
            return 1
        if not devices:
            print("未发现海康相机。", flush=True)
            return 0
        for device in devices:
            print(
                f"[{device.index}] model={device.model_name} serial={device.serial_number or '--'} layer={device.layer_type}",
                flush=True,
            )
        return 0
    migrate_legacy_runtime(PROJECT_ROOT / "runtime/vision", configured_line_id())
    app = CircleCameraApp(args)
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
