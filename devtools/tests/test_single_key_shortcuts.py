import re
import unittest
from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[2] / 'app' / '快捷键工具' /
          'CAXA_半自动辅助.ahk')


class SingleKeyShortcutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lines = SCRIPT.read_text(encoding='utf-8-sig').splitlines()
        cls.active_lines = [line.strip() for line in cls.lines
                            if line.strip() and not line.lstrip().startswith(';')]

    def test_all_daily_shortcuts_are_single_function_keys(self):
        expected = {
            'F3::fillSymbolNameField()',
            'F4::openAllLayersShortcut()',
            'F5::startSymbolDefinitionShortcut()',
            'F6::startOrNextGuideShortcut()',
            'F7::previousGuide()',
            'F8::openLayerManagerShortcut()',
            'F9::copySuggestedName()',
            'F10::safeClick("attrEdit", "属性编辑")',
            'F11::safeClick("attrFill", "填入当前标题栏属性值")',
            'F12::statusInfo()',
            'Pause::toggleAutomationPause()',
        }
        actual = {line for line in self.active_lines if '::' in line}
        self.assertEqual(actual, expected)

    def test_no_active_modifier_combo_shortcuts_remain(self):
        definitions = [line.split('::', 1)[0] for line in self.active_lines
                       if '::' in line]
        self.assertTrue(definitions)
        for key in definitions:
            self.assertFalse(re.search(r'[\^!+#<>]', key),
                             f'modifier shortcut remains active: {key}')

    def test_function_keys_are_context_gated_and_pause_is_global(self):
        script = '\\n'.join(self.active_lines)
        self.assertIn('#HotIf isCaxaTaskHotkeysActive()', script)
        self.assertIn('#HotIf isCaxaDrawingWindowActive()', script)
        self.assertIn('Pause::toggleAutomationPause()', script)
        self.assertIn('return !isPaused && isCaxaTaskProcessActive()', script)


if __name__ == '__main__':
    unittest.main(verbosity=2)
