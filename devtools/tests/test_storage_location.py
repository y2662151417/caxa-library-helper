import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import core
import ahk_runtime


class StorageLocationTests(unittest.TestCase):
    def test_core_uses_explicit_user_data_directory(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"CAXA_HELPER_DATA_DIR": td}):
                self.assertEqual(core.storage_dir(), Path(td))

    def test_ahk_runtime_uses_same_explicit_user_data_directory(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"CAXA_HELPER_DATA_DIR": td}):
                self.assertEqual(ahk_runtime._default_storage_dir(), Path(td))

    def test_relative_override_is_rejected(self):
        with patch.dict(os.environ, {"CAXA_HELPER_DATA_DIR": "relative-data"}):
            with self.assertRaises(RuntimeError):
                core.storage_dir()
            with self.assertRaises(RuntimeError):
                ahk_runtime._default_storage_dir()


if __name__ == "__main__":
    unittest.main(verbosity=2)
