from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from robot.control.controller import DEFAULTS, Runtime
import robot.debug.server as dashboard_module


class DashboardRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "servo_params.json"

    def make_runtime(self):
        runtime = Runtime(demo=True, settings_path=self.path)
        self.addCleanup(runtime.close)
        return runtime

    def test_dashboard_imports_the_production_uart_runtime(self):
        self.assertIs(dashboard_module.Runtime, Runtime)
        self.assertEqual(dashboard_module.PARAMS_PATH.name, "servo_params.json")
        self.assertEqual(dashboard_module.PARAMS_PATH.parent.name, "robot")

    def test_opening_dashboard_and_connecting_do_not_move_any_joint(self):
        runtime = self.make_runtime()
        self.assertEqual(runtime.snapshot()["logs"], [])
        runtime.connect("/dev/serial0")
        self.assertEqual(runtime.snapshot()["logs"], [])
        self.assertIsNone(runtime.snapshot()["pump_position"])

    def test_parameters_saved_by_dashboard_survive_a_new_runtime(self):
        runtime = self.make_runtime()
        params = copy.deepcopy(DEFAULTS)
        params["poses"]["pickup"][1] = 1240
        params["wait_ms"][0] = 1600
        runtime.save(params)
        restored = self.make_runtime()
        self.assertEqual(restored.snapshot()["params"], params)
        self.assertEqual(json.loads(self.path.read_text()), params)
        self.assertEqual(restored.snapshot()["logs"], [])

    def test_single_pose_command_does_not_change_pump_channel(self):
        runtime = self.make_runtime()
        params = copy.deepcopy(DEFAULTS)
        with patch.object(runtime, "send") as send, patch.object(runtime, "wait"):
            runtime.execute("move", params, pose="left_transfer")
        commands = [call.args[0] for call in send.call_args_list]
        self.assertEqual(commands, [
            b"#000P0967T1000!", b"#001P1500T1000!", b"#002P1722T1000!",
            b"#003P0722T1000!", b"#004P1500T1000!",
        ])
        self.assertIsNone(runtime.snapshot()["pump_position"])

    def test_pump_reset_is_reported_as_1500_instead_of_confirmed_off(self):
        runtime = self.make_runtime()
        with patch.object(runtime, "wait"):
            runtime.execute("pump_reset", copy.deepcopy(DEFAULTS))
        state = runtime.snapshot()
        self.assertEqual(state["pump_position"], 1500)
        self.assertFalse(state.get("arm_position_verification", False))
        self.assertTrue(any("#005P1500T1000!" in line for line in state["logs"]))


if __name__ == "__main__":
    unittest.main()
