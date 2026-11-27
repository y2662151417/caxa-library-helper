import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ExcelNameWorkflowIntegrationTests(unittest.TestCase):
    def test_only_xlsx_is_offered_for_official_name_import(self):
        source = (ROOT / "app" / "app.py").read_text(encoding="utf-8")
        start = source.index("    def import_block_names(self):")
        end = source.index("    def require(self):", start)
        body = source[start:end]
        self.assertIn("*.xlsx", body)
        self.assertIn("core.import_block_names_xlsx", body)
        self.assertNotIn("*.txt", body)
        self.assertNotIn("*.csv", body)

    def test_compact_panel_has_direct_official_name_copy_button(self):
        source = (ROOT / "app" / "floating_panel.py").read_text(encoding="utf-8")
        self.assertIn("text='复制正式块名称'", source)
        self.assertIn("self.app.copy_official_block_name(parent=self.win)", source)

    def test_property_and_insert_entry_is_not_exposed_in_actions_page(self):
        source = (ROOT / "app" / "floating_panel.py").read_text(encoding="utf-8")
        start = source.index("    def open_actions_page(self):")
        end = source.index("    def collapse_panel(self):", start)
        self.assertNotIn("属性与入库", source[start:end])
        self.assertNotIn("finish_gallery_insert", source[start:end])

    def test_automatic_property_fill_and_final_insert_are_disabled(self):
        source = (ROOT / "app" / "快捷键工具" / "CAXA_半自动辅助.ahk").read_text(encoding="utf-8-sig")
        self.assertIn("助手不会自动填写、提交、点击入库或保存", source)
        self.assertIn("助手不会点击完成按钮、提交或保存", source)
        self.assertNotIn("^!F8::fillSymbolNameField()", source)

    def test_copy_path_requires_exact_current_cad_document_check(self):
        source = (ROOT / "app" / "app.py").read_text(encoding="utf-8")
        start = source.index("    def copy_official_block_name(self,parent=None):")
        end = source.index("    def copy_name(self):", start)
        body = source[start:end]
        self.assertIn("self.verify_selected_cad_document()", body)
        self.assertIn("info['status']!='已匹配'", body)
        self.assertNotIn("suggested_name", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
