import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app'))
import core


class ViewTemplateTests(unittest.TestCase):
    def test_three_view_template_creates_six_variants(self):
        selected = core.validate_view_template(['主视图', '俯视图', '左视图'])
        self.assertEqual(selected, list(core.DEFAULT_VIEW_TEMPLATE))
        self.assertEqual(len(selected) * 2, 6)
        self.assertEqual(
            core.view_template_summary(selected),
            '主视图、俯视图、左视图｜带尺寸/无尺寸，共 6 个版本'
        )

    def test_front_and_left_template_creates_four_variants(self):
        selected = core.validate_view_template(['主视图', '左视图'])
        self.assertEqual(selected, list(core.TWO_VIEW_TEMPLATE))
        self.assertEqual(len(selected) * 2, 4)

    def test_template_order_is_stable(self):
        self.assertEqual(
            core.validate_view_template(['左视图', '主视图', '俯视图']),
            ['主视图', '俯视图', '左视图']
        )

    def test_missing_front_or_left_is_rejected(self):
        for selected in (['主视图', '俯视图'], ['左视图'], ['俯视图', '左视图']):
            with self.subTest(selected=selected):
                with self.assertRaises(ValueError):
                    core.validate_view_template(selected)

    def test_custom_or_duplicate_view_is_rejected_by_default_presets(self):
        for selected in (
            ['主视图', '左视图', '右视图'],
            ['主视图', '主视图', '左视图'],
            ['主视图'],
            [],
        ):
            with self.subTest(selected=selected):
                with self.assertRaises(ValueError):
                    core.validate_view_template(selected)


if __name__ == '__main__':
    unittest.main(verbosity=2)
