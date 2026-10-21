import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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
        rendered = format_demo_script(script)
        self.assertIn("3 分钟顾客演示脚本", rendered)
        self.assertNotIn("华为PC全板块深度知识库_v7/", rendered)
        self.assertNotIn("依据：", rendered)
        self.assertTrue(script["source_links"])
        self.assertTrue(script["source_links"][0]["url"].startswith("https://"))

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

    def test_source_sections_and_urls_are_never_used_as_product_facts(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "华为PC全板块深度知识库_v7"
            facts_path = root / "P1-产品参数库" / "HUAWEI MateBook 14" / "产品事实.md"
            facts_path.parent.mkdir(parents=True)
            facts_path.write_text(
                "# HUAWEI MateBook 14\n\n"
                "## 屏幕\n- 搭载 OLED 屏幕\n\n"
                "## 来源\n- 参考链接：https://example.test/spec\n- 支持 100W 充电\n\n"
                "## 接口\n- 提供 USB-C 接口\n",
                encoding="utf-8",
            )
            script = generate_demo_script(
                {"product": "HUAWEI MateBook 14", "customer_task": "需要屏幕和接口"},
                knowledge_base_dir=root,
            )

        claims = [fact["claim"] for fact in script["sections"][2]["evidence"]]
        self.assertTrue(any("OLED" in claim for claim in claims))
        self.assertTrue(any("USB-C" in claim for claim in claims))
        self.assertFalse(any("https://" in claim or "100W" in claim or "来源" in claim for claim in claims))


if __name__ == "__main__":
    unittest.main(verbosity=2)
