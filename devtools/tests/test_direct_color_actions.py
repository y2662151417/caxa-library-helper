import configparser
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import bridge


class DirectColorActionBridgeTests(unittest.TestCase):
    def read_request(self, action, **kwargs):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = bridge.request_panel_action(Path(directory.name), action, "a" * 64, **kwargs)
        config = configparser.ConfigParser(interpolation=None)
        config.read(path, encoding="utf-16")
        return config["request"]

    def test_each_excel_source_color_is_an_allowlisted_filter_action(self):
        for color in ("红色", "绿色", "蓝色", "洋红色", "白色+黑白色"):
            with self.subTest(color=color):
                request = self.read_request("set_pick_filter", source_color=color)
                self.assertEqual(request["action"], "set_pick_filter")
                self.assertEqual(request["source_color"], color)
                self.assertRegex(request["created_at"], r"^\\d{10}$")
                self.assertTrue(int(request["created_at"]) > 0)

    def test_filter_rejects_unknown_or_missing_color(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "颜色筛选项"):
                bridge.request_panel_action(Path(directory), "set_pick_filter", "a" * 64,
                                             source_color="黄色")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "颜色筛选项"):
                bridge.request_panel_action(Path(directory), "set_pick_filter", "a" * 64)

    def test_restore_all_colors_does_not_need_a_color_argument(self):
        request = self.read_request("restore_pick_filter")
        self.assertEqual(request["action"], "restore_pick_filter")
        self.assertNotIn("source_color", request)

    def test_apply_color_layer_requires_a_safe_excel_target(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "目标图层"):
                bridge.request_panel_action(Path(directory), "apply_color_layer", "a" * 64, source_color="红色")
        rule = dict(target_color="ByLayer", target_linetype="ByLayer",
                    linetype_scale=1.0, target_lineweight="ByLayer")
        for bad in ("", "中心线层\\n[bad]", "中心线层|bad", "x" * 65):
            with self.subTest(target=bad), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, "目标图层"):
                    bridge.request_panel_action(Path(directory), "apply_color_layer", "a" * 64,
                                                source_color="红色", target_layer=bad, **rule)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "线型比例"):
                bridge.request_panel_action(Path(directory), "apply_color_layer", "a" * 64,
                    source_color="红色", target_layer="中心线层", target_color="ByLayer", target_linetype="ByLayer",
                    linetype_scale=0, target_lineweight="ByLayer")

    def test_apply_color_layer_writes_every_excel_property(self):
        request = self.read_request("apply_color_layer", source_color="红色",
                                    target_layer="中心线层", target_color="ByLayer",
                                    target_linetype="ByLayer", linetype_scale=1.0,
                                    target_lineweight="ByLayer")
        self.assertEqual(request["action"], "apply_color_layer")
        self.assertEqual(request["target_layer"], "中心线层")
        self.assertEqual(request["target_color"], "ByLayer")
        self.assertEqual(request["target_linetype"], "ByLayer")
        self.assertEqual(request["linetype_scale"], "1.0")
        self.assertEqual(request["target_lineweight"], "ByLayer")

    def test_apply_color_layer_requires_a_source_color(self):
        rule = dict(target_layer="中心线层", target_color="ByLayer",
                    target_linetype="ByLayer", linetype_scale=1.0,
                    target_lineweight="ByLayer")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "颜色筛选项"):
                bridge.request_panel_action(Path(directory), "apply_color_layer",
                                            "a" * 64, **rule)

    def test_properties_palette_probe_is_allowlisted(self):
        request = self.read_request("probe_properties_palette")
        self.assertEqual(request["action"], "probe_properties_palette")

    def test_property_combo_calibration_actions_are_allowlisted(self):
        for action in ("calibrate_layer_combo", "calibrate_color_combo",
                       "calibrate_linetype_combo", "calibrate_lineweight_combo"):
            with self.subTest(action=action):
                request = self.read_request(action)
                self.assertEqual(request["action"], action)



class ControllerBuildHandshakeTests(unittest.TestCase):
    def test_runtime_reads_only_a_valid_build_marker(self):
        import ahk_runtime
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "ahk_controller_build.txt"
            self.assertEqual(ahk_runtime.read_controller_build(root), "")
            marker.write_text(ahk_runtime.CONTROLLER_BUILD_ID, encoding="utf-8")
            self.assertEqual(ahk_runtime.read_controller_build(root), ahk_runtime.CONTROLLER_BUILD_ID)
            marker.write_text("invalid\\nsecond-line", encoding="utf-8")
            self.assertEqual(ahk_runtime.read_controller_build(root), "")

    def test_python_and_ahk_share_the_same_controller_build_id(self):
        import ahk_runtime
        ahk = (ROOT / "app" / "快捷键工具" / "CAXA_半自动辅助.ahk").read_text(encoding="utf-8-sig")
        self.assertIn(f'global controllerBuildId := "{ahk_runtime.CONTROLLER_BUILD_ID}"', ahk)
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

    def test_panel_action_epoch_is_parsed_as_ten_digit_integer(self):
        ahk = (ROOT / "app" / "快捷键工具" / "CAXA_半自动辅助.ahk").read_text(encoding="utf-8-sig")
        self.assertIn('RegExMatch(createdAt, "^\\\\d{10}$")', ahk)
        self.assertIn('DateDiff("19700101000000", A_NowUTC, "Seconds")', ahk)
        self.assertIn("age > 300", ahk)


if __name__ == "__main__":
    unittest.main(verbosity=2)
