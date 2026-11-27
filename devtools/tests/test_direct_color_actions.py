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
                self.assertTrue(float(request["created_at"]) > 0)

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
                bridge.request_panel_action(Path(directory), "apply_color_layer", "a" * 64)
        for bad in ("", "中心线层\n[bad]", "中心线层|bad", "x" * 65):
            with self.subTest(target=bad), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, "目标图层"):
                    bridge.request_panel_action(Path(directory), "apply_color_layer", "a" * 64,
                                                target_layer=bad)

    def test_apply_color_layer_writes_the_excel_target_layer(self):
        request = self.read_request("apply_color_layer", target_layer="中心线层")
        self.assertEqual(request["action"], "apply_color_layer")
        self.assertEqual(request["target_layer"], "中心线层")

    def test_property_combo_calibration_actions_are_allowlisted(self):
        for action in ("calibrate_layer_combo", "calibrate_color_combo",
                       "calibrate_linetype_combo", "calibrate_lineweight_combo"):
            with self.subTest(action=action):
                request = self.read_request(action)
                self.assertEqual(request["action"], action)


if __name__ == "__main__":
    unittest.main(verbosity=2)
