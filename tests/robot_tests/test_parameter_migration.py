import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from robot.control import parameters


class ParameterMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.old = root / "servo_dashboard/data/servo_params.json"
        self.new = root / "runtime/robot/servo_params.json"
        self.old.parent.mkdir(parents=True)
        self.calibrated = copy.deepcopy(parameters.DEFAULTS)
        self.calibrated["poses"]["pickup"][0] = 1620
        self.calibrated["wait_ms"][0] = 1800
        self.old.write_text(json.dumps(self.calibrated))
        for name, value in (("SETTINGS", self.new), ("LEGACY_SETTINGS", self.old)):
            patcher = patch.object(parameters, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_default_location_load_preserves_calibrated_values_and_source(self):
        original_bytes = self.old.read_bytes()
        self.assertEqual(parameters.load_params(self.new), self.calibrated)
        self.assertEqual(json.loads(self.new.read_text()), self.calibrated)
        self.assertEqual(self.old.read_bytes(), original_bytes)

    def test_existing_new_parameters_win_over_old_copy(self):
        self.new.parent.mkdir(parents=True)
        self.new.write_text(json.dumps(parameters.DEFAULTS))
        self.assertEqual(parameters.load_params(self.new), parameters.DEFAULTS)
        self.assertEqual(json.loads(self.old.read_text()), self.calibrated)

    def test_corrupt_old_file_never_falls_back_to_default_positions(self):
        self.old.write_text("{")
        with self.assertRaises(ValueError):
            parameters.load_params(self.new)
        self.assertFalse(self.new.exists())
        self.assertEqual(self.old.read_text(), "{")

    def test_custom_parameter_path_does_not_import_an_unrelated_old_file(self):
        custom = self.new.parent / "custom.json"
        self.assertEqual(parameters.load_params(custom), parameters.DEFAULTS)
        self.assertFalse(custom.exists())
        self.assertFalse(self.new.exists())
