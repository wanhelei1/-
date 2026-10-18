import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.demo_script.demo_script_module import format_demo_script, generate_demo_script


class DemoScriptTests(unittest.TestCase):
    def test_generates_five_timed_sections_with_cited_product_facts(self):
        script = generate_demo_script({
            "product": "HUAWEI MateBook 14",
            "persona": "学生",
            "scenario": "学生学习",
            "customer_task": "整理课程资料并参加网课",
            "concern": "软件兼容",
            "required_software": "学校软件 4.2",
            "peripherals": "打印机型号待确认",
        })

        self.assertEqual(script["status"], "ready")
        self.assertEqual(script["duration_seconds"], 180)
        self.assertEqual(
            [section["id"] for section in script["sections"]],
            ["opening", "need_confirmation", "product_demo", "objection_handling", "close"],
        )
        demo = script["sections"][2]
        self.assertTrue(demo["evidence"])
        for fact in demo["evidence"]:
            self.assertTrue(fact["source"].startswith("华为PC全板块深度知识库_v7/"))
            self.assertGreater(fact["line_start"], 0)
        objection = script["sections"][3]["say"]
        self.assertIn("不会先承诺兼容", objection)
        self.assertIn("学校软件 4.2", script["sections"][1]["say"])
        self.assertIn("3 分钟顾客演示脚本", format_demo_script(script))

    def test_missing_product_does_not_invent_product_claims(self):
        script = generate_demo_script({"customer_task": "完成课程作业"})
        self.assertEqual(script["status"], "needs_product")
        self.assertFalse(script["sections"][2]["evidence"])
        self.assertIn("尚未确定", script["sections"][2]["say"])

    def test_unknown_product_is_marked_limited_evidence(self):
        script = generate_demo_script({"product": "不存在的产品", "concern": "预算"})
        self.assertEqual(script["status"], "limited_evidence")
        self.assertFalse(script["sections"][2]["evidence"])
        self.assertIn("不能代表门店实时成交价", script["sections"][3]["say"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
