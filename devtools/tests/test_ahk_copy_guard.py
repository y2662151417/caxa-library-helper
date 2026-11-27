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


if __name__ == "__main__":
    unittest.main(verbosity=2)
