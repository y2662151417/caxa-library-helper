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
            '默认方案：主视图、俯视图、左视图｜带尺寸/无尺寸，共 6 个版本'
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

    def test_plan_views_creates_exactly_four_or_six_database_slots(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'drawings'
            root.mkdir()
            (root / 'A-01_双视图部件.exb').write_bytes(b'fixture')
            (root / 'A-02_三视图部件.exb').write_bytes(b'fixture')
            db = core.connect(Path(td) / 'progress.sqlite3')
            try:
                self.assertEqual(core.scan_folder(db, root, exclude_dirs=()), 2)
                rows = {row['code']: row for row in core.list_drawings(db)}
                cases = (
                    ('A-01', ['主视图', '左视图'], 4),
                    ('A-02', ['主视图', '俯视图', '左视图'], 6),
                )
                for code, selected, expected in cases:
                    with self.subTest(code=code):
                        path = rows[code]['path']
                        count = core.plan_views(db, path, core.validate_view_template(selected))
                        slots = list(core.slots_for(db, path))
                        self.assertEqual(count, expected)
                        self.assertEqual(len(slots), expected)
                        self.assertEqual(
                            {slot['size_kind'] for slot in slots},
                            {'带尺寸', '无尺寸'}
                        )
            finally:
                db.close()

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
