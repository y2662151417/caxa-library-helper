import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class DirectCaxaColorAutomationSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ahk = (ROOT / "app" / "快捷键工具" / "CAXA_半自动辅助.ahk").read_text(encoding="utf-8-sig")

    def test_filter_action_sets_color_group_and_leaves_native_dialog_for_confirmation(self):
        self.assertIn('action = "set_pick_filter"', self.ahk)
        self.assertIn("setPickFilterColor(signature, sourceColor)", self.ahk)
        self.assertIn('ControlClick(noneButton, "ahk_id " dialogHwnd)', self.ahk)
        self.assertIn('ControlClick(allButton, "ahk_id " dialogHwnd)', self.ahk)
        self.assertIn('autoTip("已自动设置" sourceColor "过滤；请在 CAXA 对话框点击“确定”，再框选对象")', self.ahk)

    def test_white_and_black_filter_is_a_two_color_combination(self):
        self.assertIn('wanted := ["白", "黑"]', self.ahk)
        self.assertIn('if value = "黑色" || value = "黑白色"', self.ahk)

    def test_property_action_uses_excel_target_and_requires_a_nonempty_selection(self):
        self.assertIn('action = "apply_color_layer"', self.ahk)
        self.assertIn("applyColorLayer(signature, sourceColor, targetLayer, targetColor, targetLinetype, linetypeScale, targetLineweight)", self.ahk)
        self.assertIn("lastPickFilterSignature != expectedSignature", self.ahk)
        self.assertIn("lastPickFilterSource != sourceColor", self.ahk)
        self.assertIn("readSelectedPropertyValue(hwnd, \"layer\")", self.ahk)
        self.assertIn("readSelectedPropertyValue(hwnd, \"lineweight\")", self.ahk)
        self.assertIn("probePropertiesPalette(signature)", self.ahk)
        self.assertIn("selectionCount := readSelectedEntityCount(hwnd)", self.ahk)
        self.assertIn('if selectionCount < 1', self.ahk)
        self.assertIn('ControlChooseString value, ctrl, "ahk_id " hwnd', self.ahk)
        self.assertNotIn('runPublishedNativeCommand(signature, "properties"', self.ahk)

    def test_dialog_poll_performs_expensive_preflight_only_once(self):
        function = self.ahk.split("findPickFilterDialog(expectedSignature, workFile, mainHwnd) {", 1)[1].split("\n}", 1)[0]
        self.assertEqual(function.count("verifyBeforeAction(expectedSignature)"), 1)
        self.assertIn("IniRead(jobFile, \"active\", \"job_signature\", \"\")", function)

    def test_color_filter_verifies_all_standard_color_states(self):
        self.assertIn('expectedKeys := ["红", "黄", "绿", "青", "蓝", "洋红", "白", "黑"]', self.ahk)
        self.assertIn("state != expectedState", self.ahk)
        self.assertIn('lastPickFilterBaselineCount := baselineCount', self.ahk)

    def test_panel_request_expiry_uses_epoch_and_five_minute_ttl(self):
        self.assertIn('createdAt := IniRead(panelActionFile, "request", "created_at", "")', self.ahk)
        self.assertIn("if IsNumber(createdAt)", self.ahk)
        self.assertIn("age > 300", self.ahk)
        poll = self.ahk.split("PanelActionPoll() {", 1)[1].split("\\n}", 1)[0]
        self.assertIn("age > 300", poll)
        self.assertNotIn("age > 30 ||", poll)


if __name__ == "__main__":
    unittest.main(verbosity=2)
