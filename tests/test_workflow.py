import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from store_growth_workflow import run_customer_insight, run_store_growth_workflow


class WorkflowIntegrationTests(unittest.TestCase):
    def test_insight_stage_preserves_missing_customer_fields(self):
        result = run_customer_insight({"personas": ["学生"], "needs": ["软件兼容"]})
        self.assertEqual(result["customer"]["persona"]["status"], "已记录")
        self.assertEqual(result["customer"]["scene"]["status"], "待追问")
        self.assertTrue(result["follow_up"])

    def test_complete_flow_connects_insight_recommendation_price_and_compliance(self):
        result = run_store_growth_workflow({
            "personas": ["学生"],
            "scenes": ["学习与网课"],
            "needs": ["MateBook 14 鸿蒙版 OLED 触控屏"],
            "concerns": ["软件/外设兼容"],
            "priority_concern": "软件/外设兼容",
            "customer_words": "需要使用学校指定软件完成课程作业。",
            "customer_task": "MateBook 14 鸿蒙版 OLED 触控屏",
            "product": "HUAWEI MateBook 14",
            "platform": "小红书",
            "audience": "学生用户",
        })
        self.assertIn("customer_insight", result)
        self.assertIn("recommendation", result)
        self.assertIsNotNone(result["quote"])
        self.assertIsNotNone(result["marketing"])
        self.assertIn("compliance_review", result["marketing"])
        self.assertIn("待人工确认项", result["compliance"]["markdown"])
        self.assertEqual(result["product_selection_basis"], "user_selected")

    def test_no_selected_product_keeps_later_stages_empty(self):
        result = run_store_growth_workflow({"personas": ["教师"]})
        self.assertIsNone(result["selected_product"])
        self.assertIsNone(result["quote"])
        self.assertIsNone(result["marketing"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
