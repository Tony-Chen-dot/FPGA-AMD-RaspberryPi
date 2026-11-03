from __future__ import annotations

import copy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from robot.control.controller import DEFAULTS
import robot.actions.run_sequence as pose_module


class RecordingRuntime:
    def __init__(self):
        self.events = []
        self.failure = None
        self.device = "/dev/fake-arm"

    def connect(self, device):
        self.device = device
        self.events.append(("connect", device))

    def execute(self, action, params, target="right", pose=None):
        self.events.append(("execute", action, copy.deepcopy(params), target, pose))
        if self.failure:
            raise self.failure

    def close(self):
        self.events.append(("close",))

    def stop(self):
        self.events.append(("stop",))


class PosePumpSequenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.params_path = Path(self.temp_dir.name) / "servo_params.json"
        self.params = copy.deepcopy(DEFAULTS)
        self.runtime = RecordingRuntime()
        self.factory_patch = patch.object(pose_module, "Runtime", return_value=self.runtime)
        self.factory = self.factory_patch.start()
        self.addCleanup(self.factory_patch.stop)
        self.loader_patch = patch.object(pose_module, "load_params", return_value=self.params)
        self.loader = self.loader_patch.start()
        self.addCleanup(self.loader_patch.stop)
        self.environment_patch = patch.dict(pose_module.os.environ, {"ARM_SERIAL_PORT": "/dev/fake-arm"})
        self.environment_patch.start()
        self.addCleanup(self.environment_patch.stop)
        self.output = io.StringIO()
        self.stdout_patch = patch("sys.stdout", self.output)
        self.stdout_patch.start()
        self.addCleanup(self.stdout_patch.stop)

    def run_cli(self, *args):
        return pose_module.main([*args, "--params", str(self.params_path)])

    def execution(self):
        return [event for event in self.runtime.events if event[0] == "execute"]

    def test_camera_modes_keep_left_right_routing_and_shared_phase_parameters(self):
        for mode, direction in (("forward-left", "left"), ("forward-right", "right")):
            with self.subTest(mode=mode):
                self.runtime.events.clear()
                self.assertEqual(self.run_cli("--mode", mode, "--live"), 0)
                self.assertEqual(self.execution(), [("execute", "sequence", self.params, direction, None)])
                self.assertEqual(self.runtime.events[0], ("connect", "/dev/fake-arm"))
                self.assertEqual(self.runtime.events[-1], ("close",))
                self.assertFalse(self.factory.call_args.kwargs["demo"])

    def test_prepare_only_maps_to_reset_joints_without_extra_pump_operation(self):
        self.assertEqual(self.run_cli("--prepare-only", "--live"), 0)
        self.assertEqual(len(self.execution()), 1)
        self.assertEqual(self.execution()[0][1], "move")
        self.assertEqual(self.execution()[0][4], "reset")
        self.assertIn("STEP move preparation:", self.output.getvalue())
        self.assertNotIn("ARM position verified:", self.output.getvalue())

    def test_recovery_entry_remains_available_to_camera_failure_handler(self):
        self.assertEqual(self.run_cli("--recover", "--live"), 0)
        self.assertEqual(len(self.execution()), 1)
        self.assertEqual(self.execution()[0][1], "recover")
        self.assertEqual(self.runtime.events[-1], ("close",))

    def test_without_live_flag_runtime_is_demo(self):
        self.assertEqual(self.run_cli("--mode", "forward-right"), 0)
        self.assertTrue(self.factory.call_args.kwargs["demo"])

    def test_disable_pump_is_passed_to_same_uart_runtime(self):
        self.assertEqual(self.run_cli("--mode", "forward-left", "--disable-pump"), 0)
        self.assertFalse(self.factory.call_args.kwargs["pump_enabled"])
        self.assertEqual(self.execution()[0][1], "sequence")

    def test_uart_failure_returns_nonzero_and_closes_port_without_hidden_retry(self):
        self.runtime.failure = OSError("UART disconnected")
        code = self.run_cli("--mode", "forward-right", "--live")
        self.assertNotEqual(code, 0)
        self.assertNotIn(code, (20, 21))  # Those codes promise old relay feedback semantics to the camera.
        self.assertEqual(len(self.execution()), 1)
        self.assertEqual(self.runtime.events[-1], ("close",))

    def test_modes_remain_mutually_exclusive(self):
        with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            pose_module.build_parser().parse_args(["--mode", "forward-right", "--recover"])

    def test_default_parameter_path_is_shared_with_dashboard(self):
        path = Path(pose_module.DEFAULT_PARAMS_PATH)
        self.assertEqual(path.parts[-3:], ("runtime", "robot", "servo_params.json"))


if __name__ == "__main__":
    unittest.main()
