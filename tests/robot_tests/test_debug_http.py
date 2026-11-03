from __future__ import annotations

import copy
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch

from robot.control.controller import DEFAULTS, Runtime
import robot.debug.server as dashboard_module


class ServoDashboardHttpTests(unittest.TestCase):
    """Exercise the same browser/API boundary used by the live dashboard."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.params_path = Path(self.temp_dir.name) / "servo_params.json"
        self.runtime = Runtime(demo=True, settings_path=self.params_path)
        self.addCleanup(self.runtime.close)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard_module.handler_for(self.runtime))
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        status, content_type, page = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertTrue(content_type.startswith("text/html"))
        self.page = page
        match = re.search(r'const token = "([a-f0-9]+)"', page)
        self.assertIsNotNone(match)
        self.token = match.group(1)

    def request(self, method, path, payload=None, authenticated=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        body = None if payload is None else json.dumps(payload)
        headers = {} if payload is None else {"Content-Type": "application/json"}
        if authenticated and getattr(self, "token", None):
            headers["X-Control-Token"] = self.token
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            text = response.read().decode("utf-8")
            content_type = response.getheader("Content-Type") or ""
            result = json.loads(text) if content_type.startswith("application/json") else text
            return response.status, content_type, result
        finally:
            connection.close()

    def test_state_shares_uart_version_and_does_not_claim_position_feedback(self):
        status, content_type, body = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertTrue(content_type.startswith("application/json"))
        self.assertEqual(body["api_version"], dashboard_module.API_VERSION)
        self.assertEqual(body["params"], DEFAULTS)
        self.assertEqual(set(body["params"]["poses"]), {
            "pickup", "left_transfer", "right_transfer", "left_drop", "right_drop", "reset"
        })
        self.assertTrue(body["demo"])
        self.assertIsNone(body["pump_position"])
        self.assertFalse(body.get("arm_position_verification", False))
        self.assertIn("无状态回读", self.page)

    def test_settings_preserve_pulse_positions_and_independent_phase_timings(self):
        params = copy.deepcopy(DEFAULTS)
        params["poses"]["left_transfer"][0] = 980
        params["move_ms"][2] = 650
        params["wait_ms"][2] = 850
        status, _, body = self.request("POST", "/api/settings", {"params": params})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(json.loads(self.params_path.read_text()), params)
        self.assertEqual(self.request("GET", "/api/state")[2]["params"], params)

    def test_action_uses_the_same_shared_runtime_as_production(self):
        params = copy.deepcopy(DEFAULTS)
        with patch.object(self.runtime, "start") as start:
            status, _, body = self.request("POST", "/api/action", {
                "action": "sequence", "params": params, "target": "left"
            })
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        start.assert_called_once_with("sequence", params, "left", None)

    def test_stop_is_available_while_a_sequence_is_running(self):
        self.runtime.busy = True
        with patch.object(self.runtime, "stop") as stop:
            status, _, body = self.request("POST", "/api/stop", {})
        self.runtime.busy = False
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        stop.assert_called_once_with()

    def test_write_requires_page_control_token_and_cannot_start_motion(self):
        with patch.object(self.runtime, "start") as start:
            status, _, body = self.request("POST", "/api/action", {
                "action": "sequence", "params": DEFAULTS
            }, authenticated=False)
        self.assertEqual(status, 403)
        self.assertFalse(body["ok"])
        start.assert_not_called()

    def test_invalid_position_is_rejected_without_overwriting_settings(self):
        self.runtime.save(copy.deepcopy(DEFAULTS))
        previous = self.params_path.read_bytes()
        params = copy.deepcopy(DEFAULTS)
        params["poses"]["pickup"][0] = 90  # Old degrees must never become UART P values.
        status, _, body = self.request("POST", "/api/settings", {"params": params})
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertEqual(self.params_path.read_bytes(), previous)

    def test_export_is_absent_and_unknown_api_returns_json(self):
        self.assertNotIn("export-button", self.page)
        self.assertNotIn("/api/export", self.page)
        for path in ("/api/export", "/api/pump/not-found"):
            with self.subTest(path=path):
                status, content_type, body = self.request("POST", path, {})
                self.assertEqual(status, 404)
                self.assertTrue(content_type.startswith("application/json"))
                self.assertFalse(body["ok"])
        self.assertFalse((Path(self.temp_dir.name) / "exported_servo_params.json").exists())

    def test_runtime_rejection_is_reported_without_success(self):
        with patch.object(self.runtime, "start", side_effect=ValueError("串口未连接")):
            status, _, body = self.request("POST", "/api/action", {
                "action": "move", "params": DEFAULTS, "pose": "reset"
            })
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertIn("串口未连接", body["error"])


if __name__ == "__main__":
    unittest.main()
