import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class AHKCopyGuardTests(unittest.TestCase):
    def test_hotkey_only_copies_unique_official_name_for_matching_work_copy(self):
        source = (ROOT / "app" / "快捷键工具" / "CAXA_半自动辅助.ahk").read_text(encoding="utf-8-sig")
        start = source.index("copySuggestedName(*) {")
        end = source.index("jobWindowMatches(hwnd, workFile) {", start)
        body = source[start:end]
        self.assertIn('blockStatus != "已匹配" || blockName = ""', body)
        self.assertIn("titleHasExactWorkFile(originalTitle, workFile)", body)
        self.assertIn("A_Clipboard := blockName", body)
        self.assertNotIn("suggested_name", body)

    def test_pick_filter_and_properties_probes_are_read_only_and_task_bound(self):
        source = (ROOT / "app" / "快捷键工具" / "CAXA_半自动辅助.ahk").read_text(encoding="utf-8-sig")
        self.assertIn("probePickFilterDialog(expectedSignature, sourceColor := \"\")", source)
        self.assertIn("readSelectedEntityCount(mainHwnd)", source)
        self.assertNotIn("probePropertiesPanel(", source)
        self.assertIn("仅包含该对话框的控件文字、类别、ID、勾选状态与位置", source)
        self.assertIn("未读取主绘图区控件", source)
        self.assertIn("sourceColor := IniRead(panelActionFile, \"request\", \"source_color\", \"\")", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
