import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from follow_up_module import (
    create_plan,
    load_plans,
    save_plans,
    task_due_label,
    update_plan_status,
    update_task,
)


class FollowUpModuleTests(unittest.TestCase):
    def test_create_plan_builds_four_stages_without_identity_fields(self):
        plan = create_plan("2026-10-18", channel="微信", sequence=2)
        self.assertEqual(plan["label"], "线索-20261018-002")
        self.assertEqual([task["date"] for task in plan["tasks"]], [
            "2026-10-18", "2026-10-19", "2026-10-21", "2026-10-25",
        ])
        self.assertEqual(len(plan["tasks"]), 4)
        self.assertNotIn("name", plan)
        self.assertNotIn("phone", plan)

    def test_updates_validate_status_channel_date_and_text(self):
        plan = create_plan("2026-10-18")
        update_task(plan, 1, status="已联系", date_value="2026-10-20", channel="电话", note="已答复")
        self.assertEqual(plan["tasks"][0]["status"], "已联系")
        self.assertEqual(plan["tasks"][0]["date"], "2026-10-20")
        self.assertEqual(task_due_label(plan["tasks"][1], date(2026, 10, 18)), "待到期")
        with self.assertRaises(ValueError):
            update_task(plan, 1, status="已购买")
        with self.assertRaises(ValueError):
            update_task(plan, 1, channel="私聊平台")
        with self.assertRaises(ValueError):
            update_task(plan, 1, date_value="18/10/2026")
        with self.assertRaises(ValueError):
            update_task(plan, 5, status="已联系")

    def test_plan_status_and_json_persistence(self):
        plan = update_plan_status(create_plan("2026-10-18"), "停止联系")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plans.json"
            save_plans(path, [plan])
            self.assertEqual(load_plans(path), [plan])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))[0]["status"], "停止联系")
        with self.assertRaises(ValueError):
            update_plan_status(plan, "推进成交")


if __name__ == "__main__":
    unittest.main(verbosity=2)
