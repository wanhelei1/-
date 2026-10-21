import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.workflow.store_growth_workflow import run_customer_insight, run_store_growth_workflow


class WorkflowIntegrationTests(unittest.TestCase):
    def test_insight_stage_preserves_missing_customer_fields(self):
        result = run_customer_insight({"personas": ["学生"], "needs": ["软件兼容"]})
        self.assertEqual(result["customer"]["persona"]["status"], "已记录")
        self.assertEqual(result["customer"]["scene"]["status"], "待追问")
        self.assertTrue(result["follow_up"])

    def test_insight_preserves_multiple_priority_concerns_in_order(self):
        result = run_customer_insight({
            "needs": ["学习资料整理"],
            "concerns": ["预算与价格", "软件与外设兼容", "便携与续航"],
            "priority_concerns": ["预算与价格", "软件与外设兼容"],
        })
        customer = result["customer"]
        self.assertEqual(customer["priority_concerns"], ["预算与价格", "软件和外设能否使用"])
        self.assertEqual(customer["priority_concern"], "预算与价格、软件和外设能否使用")

    def test_legacy_single_priority_concern_remains_supported(self):
        result = run_customer_insight({
            "needs": ["软件兼容"],
            "concerns": ["软件/外设兼容"],
            "priority_concern": "软件/外设兼容",
        })
        self.assertEqual(result["customer"]["priority_concerns"], ["软件和外设能否使用"])

    def test_removed_and_nested_priority_concerns_are_normalized(self):
        result = run_customer_insight({
            "needs": ["日常办公"],
            "priority_concerns": [
                "数据安全",
                "便携与续航",
                "屏幕与触控体验",
                "接口连接",
                "性能与配置",
            ],
        })
        self.assertEqual(
            result["customer"]["priority_concerns"],
            ["日常使用体验", "性能是否够用"],
        )

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
        self.assertIn("demo_script", result)
        self.assertEqual(result["demo_script"]["duration_seconds"], 180)
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

    def test_unrecorded_insight_placeholders_do_not_become_recommendation_inputs(self):
        result = run_store_growth_workflow({"personas": ["教师"]})
        plan = result["recommendation"]["plan"]
        self.assertEqual(plan["retrieval_status"], "invalid_input")
        explicit = plan["customer_facts"]["explicit"]
        self.assertEqual(explicit["客户需求描述"], "")
        self.assertEqual(explicit["使用场景"], "")
        self.assertNotIn("尚未提供", " ".join(str(value) for value in explicit.values()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
