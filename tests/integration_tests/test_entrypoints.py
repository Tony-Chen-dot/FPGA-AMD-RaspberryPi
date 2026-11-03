import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class EntrypointTests(unittest.TestCase):
    def test_cli_help_works_outside_project_directory_without_opening_hardware(self):
        with tempfile.TemporaryDirectory() as directory:
            for relative_path in (
                "vision/pipeline.py",
                "robot/actions/run_sequence.py",
                "robot/debug/server.py",
                "tools/simulate_device.py",
            ):
                with self.subTest(entrypoint=relative_path):
                    result = subprocess.run(
                        [sys.executable, str(PROJECT_ROOT / relative_path), "--help"],
                        cwd=directory,
                        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                        capture_output=True, text=True, timeout=15,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("--help", result.stdout)
