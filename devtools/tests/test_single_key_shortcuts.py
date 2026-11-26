import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "app" / "快捷键工具" / "CAXA_半自动辅助.ahk"
PANEL = ROOT / "app" / "floating_panel.py"


class FloatingPanelControlsTests(unittest.TestCase):
    def test_controller_does_not_register_or_intercept_hotkeys(self):
        lines = SCRIPT.read_text(encoding="utf-8-sig").splitlines()
        active_hotkeys = [line.strip() for line in lines
                          if "::" in line and not line.lstrip().startswith(";")]
        self.assertEqual(active_hotkeys, [])
        source = SCRIPT.read_text(encoding="utf-8-sig")
        self.assertNotIn("#HotIf", source)

    def test_home_panel_exposes_frequent_operations_directly(self):
        source = PANEL.read_text(encoding="utf-8")
        home = source[source.index("def _show_home_page"):source.index("def open_actions_page")]
        self.assertIn("常用操作（直接点击）", home)
        for label in ("清理重复线", "颜色归层", "打开图层设置",
                      "全部图层打开", "定义图符", "属性与入库"):
            self.assertIn(label, home)
        self.assertIn("self.delete_duplicate_lines", home)
        self.assertIn("self.open_cleanup_window", home)
        self.assertIn("self.define_symbol", home)
        self.assertIn("self.open_insert_window", home)

    def test_shortcuts_are_not_described_as_required_in_settings(self):
        source = PANEL.read_text(encoding="utf-8")
        start = source.index("def open_settings_window")
        end = source.index("\\n    def ", start + 1)
        settings = source[start:end]
        self.assertIn("常用功能已直接放在悬浮面板首页", settings)
        self.assertIn("本版本不拦截 CAXA 原生快捷键", settings)
        self.assertNotIn("F3", settings)
        self.assertNotIn("Pause", settings)


if __name__ == "__main__":
    unittest.main(verbosity=2)
