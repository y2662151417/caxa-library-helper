import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import ahk_runtime


class ControllerBuildHandshakeTests(unittest.TestCase):
    def test_runtime_reads_only_a_valid_build_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "ahk_controller_build.txt"
            self.assertEqual(ahk_runtime.read_controller_build(root), "")
            marker.write_text(ahk_runtime.CONTROLLER_BUILD_ID, encoding="utf-8")
            self.assertEqual(
                ahk_runtime.read_controller_build(root),
                ahk_runtime.CONTROLLER_BUILD_ID,
            )
            marker.write_text("invalid\nsecond-line", encoding="utf-8")
            self.assertEqual(ahk_runtime.read_controller_build(root), "")

    def test_python_and_ahk_share_the_same_controller_build_id(self):
        ahk = (ROOT / "app" / "快捷键工具" / "CAXA_半自动辅助.ahk").read_text(encoding="utf-8-sig")
        self.assertIn(
            f'global controllerBuildId := "{ahk_runtime.CONTROLLER_BUILD_ID}"',
            ahk,
        )
        self.assertIn('FileAppend controllerBuildId, controllerBuildMarker, "UTF-8-RAW"', ahk)
        self.assertIn('FileDelete controllerBuildMarker', ahk)

    def test_runtime_waits_for_matching_pid_and_build_marker(self):
        runtime = (ROOT / "app" / "ahk_runtime.py").read_text(encoding="utf-8")
        self.assertIn("read_controller_pid(root) == proc.pid", runtime)
        self.assertIn("read_controller_build(root) == CONTROLLER_BUILD_ID", runtime)

    def test_panel_blocks_actions_if_an_old_controller_is_still_running(self):
        panel = (ROOT / "app" / "floating_panel.py").read_text(encoding="utf-8")
        self.assertIn("build=ahk_runtime.read_controller_build(core.storage_dir())", panel)
        self.assertIn("build!=ahk_runtime.CONTROLLER_BUILD_ID", panel)
        self.assertIn("检测到旧版 CAXA 控制器", panel)
        self.assertIn("return False", panel)

    def test_panel_action_epoch_is_parsed_as_ten_digit_integer(self):
        ahk = (ROOT / "app" / "快捷键工具" / "CAXA_半自动辅助.ahk").read_text(encoding="utf-8-sig")
        self.assertIn('RegExMatch(createdAt, "^\\d{10}$")', ahk)
        self.assertIn('DateDiff("19700101000000", A_NowUTC, "Seconds")', ahk)
        self.assertIn("age > 300", ahk)


if __name__ == "__main__":
    unittest.main(verbosity=2)
