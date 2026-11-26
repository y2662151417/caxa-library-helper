import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import router_v11


def drawing(**overrides):
    row = {
        "present": True,
        "valid_name": True,
        "status": "处理中",
        "suggested_name": "A-01_机架",
        "naming_mode": "其他图纸（人工确认）",
    }
    row.update(overrides)
    return row


def slots(count, status="待处理"):
    views = ["主视图", "左视图"] if count == 4 else ["主视图", "俯视图", "左视图"]
    return [
        {"view_type": view, "size_kind": kind, "status": status}
        for kind in ("带尺寸", "无尺寸")
        for view in views
    ]


class RouterTaskRunnerTests(unittest.TestCase):
    def test_pending_four_view_plan_starts_symdef_directly(self):
        action = router_v11.choose(
            drawing(), work_exists=True, slots=slots(4),
            configured_views=True, changed=False
        )
        self.assertEqual(action.key, "define_symbol")
        self.assertIn("4项", action.label)
        self.assertNotIn("提示", action.label)

    def test_pending_six_view_plan_starts_symdef_directly(self):
        action = router_v11.choose(
            drawing(), work_exists=True, slots=slots(6),
            configured_views=True, changed=False
        )
        self.assertEqual(action.key, "define_symbol")
        self.assertIn("6项", action.label)
        self.assertIn("无需返回助手", action.reason)

    def test_unexpected_view_count_is_blocked(self):
        action = router_v11.choose(
            drawing(), work_exists=True, slots=slots(4)[:3],
            configured_views=True, changed=False
        )
        self.assertEqual(action.key, "blocked")
        self.assertIn("视图计划异常", action.label)

    def test_all_reviewed_slots_route_to_review(self):
        action = router_v11.choose(
            drawing(), work_exists=True, slots=slots(4, "已复核"),
            configured_views=True, changed=False
        )
        self.assertEqual(action.key, "review")

    def test_no_slots_starts_production_from_saved_template(self):
        action = router_v11.choose(
            drawing(), work_exists=True, slots=[],
            configured_views=True, changed=False
        )
        self.assertEqual(action.key, "prepare_views")
        self.assertEqual(action.label, "开始制作本张图纸")
        self.assertIn("直接启动", action.reason)

    def test_missing_work_copy_precedes_cad_actions(self):
        action = router_v11.choose(
            drawing(), work_exists=False, slots=slots(6),
            configured_views=True, changed=False
        )
        self.assertEqual(action.key, "open_copy")

    def test_completed_drawing_routes_to_next(self):
        action = router_v11.choose(
            drawing(status="已人工复核"), work_exists=True, slots=slots(4),
            configured_views=True, changed=False
        )
        self.assertEqual(action.key, "next")


if __name__ == "__main__":
    unittest.main(verbosity=2)
