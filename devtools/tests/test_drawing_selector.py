import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CompactDrawingSelectorTests(unittest.TestCase):
    def test_selector_exposes_only_the_daily_selection_flow(self):
        source = (ROOT / "app" / "drawing_selector.py").read_text(encoding="utf-8")
        self.assertIn('self.win.title("选择图纸")', source)
        self.assertIn('text="打开图纸"', source)
        self.assertIn('text="选择目录"', source)
        self.assertIn('text="搜索图号／图名："', source)
        self.assertIn('self.tree.bind("<Double-1>"', source)
        self.assertNotIn("备份记录", source)
        self.assertNotIn("导出汇总CSV", source)
        self.assertNotIn("参数提取", source)
        self.assertNotIn("人工验收清单", source)

    def test_mini_launcher_hides_advanced_root(self):
        source = (ROOT / "app" / "app.py").read_text(encoding="utf-8")
        self.assertIn("self.mini_mode = os.environ.get('CAXA_MINI_PANEL') == '1'", source)
        self.assertIn("if self.mini_mode:\n            self.root.withdraw()", source)
        self.assertIn("def open_drawing_selector(self):", source)
        self.assertIn("def open_admin_workbench(self):", source)

    def test_work_copy_action_reports_success_to_selector(self):
        source = (ROOT / "app" / "app.py").read_text(encoding="utf-8")
        start = source.index("    def open_work_copy(self):")
        end = source.index("    def open_file(", start)
        body = source[start:end]
        self.assertIn("return self.open_file(file_to_open=copy)", body)
        self.assertIn("return False", body)
        selector = (ROOT / "app" / "drawing_selector.py").read_text(encoding="utf-8")
        self.assertIn("if self.app.open_work_copy():", selector)

    def test_floating_panel_opens_selector_not_full_workbench(self):
        source = (ROOT / "app" / "floating_panel.py").read_text(encoding="utf-8")
        start = source.index("    def open_workbench(self):")
        end = source.index("    def _dialog(", start)
        body = source[start:end]
        self.assertIn("self.app.open_drawing_selector()", body)
        self.assertNotIn("self.app.root.deiconify()", body)
        self.assertIn("def suspend_topmost(self):", source)
        self.assertIn("def resume_topmost(self):", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
