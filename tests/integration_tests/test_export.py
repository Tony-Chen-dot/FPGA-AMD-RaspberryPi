"""A distributable export includes its license, documentation and entrypoints."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ExportTests(unittest.TestCase):
    def test_export_can_be_distributed_and_checked_without_runtime_state(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)/'raspberry_pi'
            result = subprocess.run(
                [sys.executable, '-B', str(ROOT/'tools/export_raspberry_pi.py'), str(destination)],
                capture_output=True, text=True,
                env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for path in ['license', 'readme.md', 'sim/verify.sh', 'board/readme.md',
                         'skill/readme.md', 'report/third_party_notices.md', 'start_all.sh']:
                with self.subTest(path=path):
                    self.assertTrue((destination/path).is_file())
            self.assertFalse((destination/'runtime').exists())
            self.assertFalse((destination/'.git').exists())
            self.assertIn('DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}"',
                          (destination/'config.sh').read_text(encoding='utf-8'))
            for path in destination.rglob('*'):
                self.assertRegex(path.name, r'^[a-z0-9_.-]+$')


if __name__ == '__main__':
    unittest.main()
