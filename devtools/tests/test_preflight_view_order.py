import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import bridge
import core
import preflight


class PublishedViewOrderTests(unittest.TestCase):
    def _publish_task(self, folder, selected_views, *, interleaved=False):
        root = Path(folder)
        drawings = root / "source"
        drawings.mkdir(parents=True, exist_ok=True)
        source = drawings / "T-01_虚构测试图.exb"
        source.write_bytes(b"synthetic test bytes; not a real EXB file")

        db = core.connect(root / "progress.sqlite3")
        self.assertEqual(core.scan_folder(db, drawings, exclude_dirs=()), 1)
        source_path = str(source)
        core.save_custom_name(db, source_path, source.stem + "_本地测试名称")
        core.plan_views(db, source_path, list(selected_views))
        core.ensure_working_copy(db, source_path)

        drawing = core.get_drawing(db, source_path)
        slots = list(core.slots_for(db, source_path))
        if interleaved:
            plan = tuple(
                f"{view}·{kind}"
                for view in core.VIEW_TYPES
                for kind in ("带尺寸", "无尺寸")
                for slot in slots
                if slot["view_type"] == view
                and slot["size_kind"] == kind
                and slot["status"] != "不需要"
            )
        else:
            plan = tuple(
                f"{slot['view_type']}·{slot['size_kind']}"
                for slot in slots
                if slot["status"] != "不需要"
            )

        block = core.block_name_for_path(db, source_path)
        storage = root / "user_data"
        bridge.publish_active_job(
            storage,
            drawing,
            drawing["suggested_name"],
            plan,
            block["block_name"],
            block["status"],
        )
        signature = bridge.expected_job_signature(
            drawing,
            drawing["suggested_name"],
            plan,
            block["block_name"],
            block["status"],
        )
        return db, storage, signature, plan

    def test_canonical_order_is_accepted_for_two_and_three_view_templates(self):
        cases = (
            (core.TWO_VIEW_TEMPLATE,
             ("主视图·带尺寸", "左视图·带尺寸", "主视图·无尺寸", "左视图·无尺寸")),
            (core.DEFAULT_VIEW_TEMPLATE,
             ("主视图·带尺寸", "俯视图·带尺寸", "左视图·带尺寸",
              "主视图·无尺寸", "俯视图·无尺寸", "左视图·无尺寸")),
        )
        for selected_views, expected_plan in cases:
            with self.subTest(selected_views=selected_views), tempfile.TemporaryDirectory() as td:
                db, storage, signature, plan = self._publish_task(td, selected_views)
                try:
                    self.assertEqual(plan, expected_plan)
                    self.assertTrue(
                        preflight.active_job_valid(db, storage, signature),
                        "a correctly published production-order task must pass the independent verifier",
                    )
                finally:
                    db.close()

    def test_basic_work_copy_task_is_valid_without_a_view_plan_or_name(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            drawings = root / "source"
            drawings.mkdir()
            source = drawings / "BASIC-01_普通测试图.exb"
            source.write_bytes(b"synthetic test bytes; not a real EXB file")
            db = core.connect(root / "progress.sqlite3")
            try:
                self.assertEqual(core.scan_folder(db, drawings, exclude_dirs=()), 1)
                core.ensure_working_copy(db, str(source))
                drawing = core.get_drawing(db, str(source))
                block = core.block_name_for_path(db, str(source))
                storage = root / "user_data"
                bridge.publish_active_job(
                    storage, drawing, drawing["suggested_name"], (),
                    block["block_name"], block["status"]
                )
                signature = bridge.expected_job_signature(
                    drawing, drawing["suggested_name"], (),
                    block["block_name"], block["status"]
                )
                self.assertTrue(
                    preflight.active_job_valid(db, storage, signature),
                    "basic layer and cleanup actions must not require a six-view plan",
                )
            finally:
                db.close()

    def test_interleaved_view_order_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            db, storage, signature, plan = self._publish_task(
                td, core.DEFAULT_VIEW_TEMPLATE, interleaved=True
            )
            try:
                self.assertNotEqual(
                    plan,
                    ("主视图·带尺寸", "俯视图·带尺寸", "左视图·带尺寸",
                     "主视图·无尺寸", "俯视图·无尺寸", "左视图·无尺寸"),
                )
                self.assertFalse(
                    preflight.active_job_valid(db, storage, signature),
                    "an out-of-order task must remain blocked",
                )
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
