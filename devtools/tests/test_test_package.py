import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "devtools" / "release"))
from build_test_package import build_test_package


class IsolatedTestPackageTests(unittest.TestCase):
    def test_package_has_one_launcher_and_no_development_or_user_files(self):
        with tempfile.TemporaryDirectory() as temp:
            zip_path, checksum_path = build_test_package(ROOT, Path(temp))
            self.assertTrue(checksum_path.is_file())
            with zipfile.ZipFile(zip_path) as archive:
                names = archive.namelist()
                root = "CAXA_图库助手_v0.42.16_独立测试版/"
                top_files = [
                    name for name in names
                    if name.startswith(root)
                    and "/" not in name[len(root):]
                ]
                self.assertEqual(top_files, [root + "启动CAXA助手.bat"])
                self.assertFalse(any("/devtools/" in name or "/.github/" in name for name in names))
                self.assertFalse(any(name.lower().endswith(
                    (".exb", ".dwg", ".dxf", ".sqlite", ".sqlite3", ".db", ".pyc")
                ) for name in names))
                self.assertIn(root + "app/floating_panel.py", names)
                self.assertIn(root + "runtime/launcher.py", names)
                self.assertIn(root + "docs/测试版使用说明_v0.42.16.md", names)

    def test_launcher_uses_separate_profile_and_updates_are_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            zip_path, _ = build_test_package(ROOT, Path(temp))
            with zipfile.ZipFile(zip_path) as archive:
                root = "CAXA_图库助手_v0.42.16_独立测试版/"
                launcher = archive.read(root + "启动CAXA助手.bat").decode("utf-8-sig")
                self.assertIn(
                    "CAXA_Library_Helper_TEST_0_42_16",
                    launcher,
                )
                self.assertNotIn(
                    r"\CAXA_Library_Helper""",
                    launcher,
                )
                self.assertNotIn(r"UserData\.caxa_userdata.json", launcher)
                config = json.loads(
                    archive.read(root + "updates/update_source.json").decode("utf-8")
                )
                self.assertIs(config["auto_check"], False)
                self.assertEqual(config["manifest_url"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
