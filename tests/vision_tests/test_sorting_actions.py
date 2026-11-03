from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CIRCLE_CAMERA_DIR = PROJECT_ROOT / "vision"
if str(CIRCLE_CAMERA_DIR) not in sys.path:
    sys.path.insert(0, str(CIRCLE_CAMERA_DIR))

SPEC = importlib.util.spec_from_file_location("circle_camera_main", CIRCLE_CAMERA_DIR / "pipeline.py")
assert SPEC is not None and SPEC.loader is not None
circle_camera_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = circle_camera_module
SPEC.loader.exec_module(circle_camera_module)


class CircleCameraActionTests(unittest.TestCase):
    def test_trigger_identity_uses_utc_timestamp_and_safe_frame_id(self) -> None:
        timestamp, artifact_token, frame_id = circle_camera_module.create_trigger_identity(
            datetime(2026, 8, 20, 19, 12, 30, 932407, tzinfo=timezone.utc)
        )

        self.assertEqual(timestamp, "2026-08-20T19:12:30.932407+00:00")
        self.assertEqual(artifact_token, "20260820_191230_932407")
        self.assertEqual(frame_id, "circle-20260820_191230_932407")

    def make_action_app(self):
        app = object.__new__(circle_camera_module.CircleCameraApp)
        app.project_dir = CIRCLE_CAMERA_DIR
        app.args = SimpleNamespace(
            disable_arm_action=False,
            action_direction_mode=0,
            action_delay_seconds=0.0,
            pose_runner_path="robot/actions/run_sequence.py",
            action_params_path="runtime/robot/servo_params.json",
            action_python="/usr/bin/python3",
            action_hold_seconds=0.2,
            action_pump_before_seconds=0.1,
            action_pump_after_seconds=0.7,
            action_live=True,
            action_timeout_seconds=30.0,
        )
        messages: list[str] = []
        app.log = messages.append
        return app, messages

    def test_production_action_uses_dashboard_parameter_file_timings(self) -> None:
        app, messages = self.make_action_app()

        completed = SimpleNamespace(returncode=0)
        with patch.object(circle_camera_module.time, "monotonic", return_value=0.0), patch.object(
            circle_camera_module.subprocess,
            "run",
            return_value=completed,
        ) as run:
            app._run_pose_action_for_result("NG", trigger_started_at=0.0)

        command = run.call_args.args[0]
        self.assertIn("forward-left", command)
        self.assertNotIn("--hold", command)
        self.assertNotIn("--pump-before-seconds", command)
        self.assertNotIn("--pump-after-seconds", command)
        self.assertIn("servo_params.json", command[command.index("--params") + 1])
        self.assertIn("--live", command)
        self.assertTrue(any("timings=dashboard_params" in message for message in messages))
        self.assertNotIn("capture_output", run.call_args.kwargs)

    def test_action_failure_runs_recovery_mode(self) -> None:
        app, messages = self.make_action_app()
        completed = SimpleNamespace(returncode=0)
        with patch.object(circle_camera_module.time, "monotonic", return_value=0.0), patch.object(
            circle_camera_module.subprocess,
            "run",
            side_effect=[subprocess.TimeoutExpired("pose", 30), completed],
        ) as run:
            app._run_pose_action_for_result("NG", trigger_started_at=0.0)

        self.assertEqual(run.call_count, 2)
        recovery_command = run.call_args_list[1].args[0]
        self.assertIn("--recover", recovery_command)
        self.assertIn("--live", recovery_command)
        self.assertTrue(any("安全恢复完成" in message for message in messages))

    def test_uart_command_failure_runs_recovery(self) -> None:
        app, messages = self.make_action_app()
        with patch.object(circle_camera_module.time, "monotonic", return_value=0.0), patch.object(
            circle_camera_module.subprocess, "run",
            side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)],
        ) as run:
            succeeded = app._run_pose_action_for_result("NG", trigger_started_at=0.0, action_tag="A001")
        self.assertFalse(succeeded)
        self.assertEqual(run.call_count, 2)
        self.assertIn("--recover", run.call_args_list[1].args[0])

    def test_unrecognized_parameters_use_configured_timeout(self) -> None:
        app, _messages = self.make_action_app()
        app.args.action_timeout_seconds = 5.0
        with tempfile.TemporaryDirectory() as directory:
            params_path = Path(directory) / "params.json"
            params_path.write_text(
                '{"move_ms":700,"transitions_ms":{'
                '"preparation_to_forward":3000,"forward_to_left":3000,'
                '"left_to_preparation":3000},"pump_seconds":{'
                '"forward_hold":0.2,"target_before_off":0.1,"target_after_off":0.7}}',
                encoding="utf-8",
            )

            timeout_seconds = app._action_timeout_seconds(params_path, "left")

        self.assertEqual(timeout_seconds, 5.0)

    def test_uart_timeout_uses_five_waits_without_double_counting_T(self) -> None:
        import json
        app, _ = self.make_action_app()
        app.args.action_timeout_seconds = 5
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "params.json"
            path.write_text(json.dumps({"move_ms": [9999] * 5, "wait_ms": [10000] * 5}))
            self.assertEqual(app._action_timeout_seconds(path, "left"), 55.0)

    def test_uart_recovery_timeout_covers_release_and_reset_waits(self) -> None:
        import json
        app, _ = self.make_action_app()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "params.json"
            path.write_text(json.dumps({"move_ms": [1000] * 5, "wait_ms": [0, 0, 0, 20000, 30000]}))
            with patch.object(circle_camera_module.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
                app._run_pose_recovery(PROJECT_ROOT, PROJECT_ROOT / "robot/actions/run_sequence.py", path)
            self.assertEqual(run.call_args.kwargs["timeout"], 55.0)

    def test_trigger_fifo_accepts_two_consecutive_jobs(self) -> None:
        app = object.__new__(circle_camera_module.CircleCameraApp)
        app.args = SimpleNamespace(center_threshold_px=1)

        class RecordingWorker:
            def __init__(self) -> None:
                self.calls = []
                self.capacity = 8

            @property
            def depth(self):
                return len(self.calls)

            def submit(self, task):
                self.calls.append(task)
                return True

        app.trigger_worker = RecordingWorker()
        app.log = lambda _message: None
        frame = np.zeros((20, 20, 3), dtype=np.uint8)
        gray = np.zeros((20, 20), dtype=np.uint8)
        circle = circle_camera_module.CircleDetection(
            x=10,
            y=10,
            radius=5,
            distance_to_center=0.0,
            circularity=1.0,
            edge_support=1.0,
            fill_ratio=1.0,
            radial_error_ratio=0.0,
            angular_coverage=1.0,
            diameter_ratio=0.5,
            score=1.0,
            source="test",
        )

        with patch.object(circle_camera_module, "annotate_frame", side_effect=lambda image, *_args: image):
            self.assertTrue(app.save_trigger_bundle(frame, gray, [circle], circle))
            self.assertTrue(app.save_trigger_bundle(frame, gray, [circle], circle))

        self.assertEqual(len(app.trigger_worker.calls), 2)

    def test_action_worker_propagates_failure_without_trigger_state(self) -> None:
        app = object.__new__(circle_camera_module.CircleCameraApp)
        app._run_pose_action_for_result = lambda *_args: (_ for _ in ()).throw(RuntimeError("failed"))
        app.args = SimpleNamespace(action_delay_seconds=0.0)
        app.action_worker = SimpleNamespace(in_flight=1, capacity=3, depth=0)
        app.log = lambda _message: None

        with self.assertRaisesRegex(RuntimeError, "failed"):
            app._process_action_task(
                circle_camera_module.ActionTask(
                    action_id=1,
                    frame_id="test-frame",
                    result_label="NG",
                    trigger_monotonic=0.0,
                    enqueued_monotonic=0.0,
                )
            )

if __name__ == "__main__":
    unittest.main()
