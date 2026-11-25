import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))
import prepare_data


class StartupDataPreflightTests(unittest.TestCase):
    def test_creates_and_writes_user_data_logs(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "UserData"
            actual_data, log_dir = prepare_data.prepare_data_directory(data_dir)
            self.assertEqual(actual_data, data_dir)
            self.assertTrue(log_dir.is_dir())
            self.assertIn(
                "write check passed",
                (log_dir / "startup.log").read_text(encoding="utf-8"),
            )

    def test_rejects_relative_user_data_path(self):
        with self.assertRaises(ValueError):
            prepare_data.prepare_data_directory("relative-user-data")

    def test_startup_batch_uses_python_preflight(self):
        batch = (ROOT / "启动CAXA助手.bat").read_text(encoding="utf-8")
        self.assertIn('%PY% "runtime\\prepare_data.py"', batch)
        self.assertNotIn("\\logs\\NUL", batch)


if __name__ == "__main__":
    unittest.main(verbosity=2)
