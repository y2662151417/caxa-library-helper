import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CaxaNativeControlStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ahk = (ROOT / "app" / "快捷键工具" / "CAXA_半自动辅助.ahk").read_text(encoding="utf-8-sig")

    def test_filter_matching_requires_native_checkbox_styles(self):
        function = self.ahk.split("findFilterCheckbox(labelItem, items, gx, gy, gr, gb) {", 1)[1].split("\n}", 1)[0]
        self.assertIn('isNativeCheckboxStyle(labelItem["class"], labelItem["style"])', function)
        self.assertIn('isNativeCheckboxStyle(item["class"], item["style"])', function)
        self.assertNotIn('labelItem["checked"] >= 0', function)
        self.assertIn("buttonType = 2 || buttonType = 3 || buttonType = 5 || buttonType = 6", self.ahk)

    def test_color_group_requires_native_groupbox_style(self):
        self.assertIn("isNativeGroupBoxStyle(className, style)", self.ahk)
        self.assertIn('return className = "Button" && (style & 0xF) = 7', self.ahk)

    def test_read_only_probe_records_control_style(self):
        self.assertIn('styleText := Format("0x{:X}", style)', self.ahk)
        self.assertIn('Style=" . styleText', self.ahk)


if __name__ == "__main__":
    unittest.main(verbosity=2)
