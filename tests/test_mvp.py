import json
import sys
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app


class MvpDataTests(unittest.TestCase):
    def test_catalog_and_scenario_are_loaded_from_knowledge_base(self):
        products = app._catalog()
        self.assertGreaterEqual(len(products), 8)
        self.assertTrue(any("HUAWEI MateBook 14" == p["id"] for p in products))
        self.assertGreaterEqual(len(app._scenario_questions("门店零售")), 3)

    def test_consult_keeps_compatibility_as_unverified(self):
        result = app._consult({
            "scenario": "门店零售",
            "customer_task": "轮班顾问要完成产品演示和客户资料交接",
            "required_software": "会员系统 4.2",
            "peripherals": "票据打印机型号待查",
            "product": "HUAWEI MateBook 14",
        })
        self.assertIn("不输出无证据", result["decision"])
        self.assertEqual(result["requirements"][1]["status"], "待验证")
        self.assertEqual(result["requirements"][2]["status"], "待验证")
        self.assertTrue(result["product_evidence"]["facts"])
        self.assertIsNotNone(result["quote"])

    def test_marketing_uses_exact_official_image_sources(self):
        result = app.generate_marketing_content(
            "HUAWEI MateBook 14", "小红书", "学生用户",
            knowledge_base_dir=app.KB,
        )
        self.assertTrue(result["evidence_facts"])
        self.assertTrue(result["recommended_images"])
        for image in result["recommended_images"]:
            self.assertTrue(image["image_url"].startswith("https://"))
            self.assertTrue(image["page_url"].startswith("https://"))
        self.assertTrue(result["sources"])
        self.assertFalse(result["compliance"]["dynamic_price_or_inventory_included"])

    def test_unknown_product_does_not_invent_facts_or_images(self):
        result = app.generate_marketing_content(
            "不存在的型号", "知乎", "教师用户", knowledge_base_dir=app.KB,
        )
        self.assertFalse(result["evidence_facts"])
        self.assertFalse(result["recommended_images"])
        self.assertTrue(result["warnings"])

    def test_unknown_platform_is_rejected(self):
        with self.assertRaises(ValueError):
            app.generate_marketing_content("MateBook 14", "Instagram", knowledge_base_dir=app.KB)


class HttpSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from threading import Thread
        cls.server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:%s" % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def post(self, path, payload):
        request = Request(self.base + path, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"})
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())

    def test_health_and_bootstrap(self):
        with urlopen(self.base + "/health", timeout=5) as response:
            data = json.loads(response.read().decode())
        self.assertTrue(data["ok"])
        with urlopen(self.base + "/api/bootstrap", timeout=5) as response:
            boot = json.loads(response.read().decode())
        self.assertFalse(boot["api_key_required"])
        self.assertTrue(boot["products"])

    def test_consult_marketing_and_quote_endpoints(self):
        consult = self.post("/api/consult", {"scenario":"学生学习", "product":"HUAWEI MateBook 14", "customer_task":"整理课程资料"})
        self.assertTrue(consult["scenario_questions"])
        marketing = self.post("/api/marketing", {"product":"HUAWEI MateBook 14", "platform":"小红书", "audience":"学生用户"})
        self.assertIn("title", marketing)
        quote = self.post("/api/quote", {"product":"HUAWEI MateBook 14"})
        self.assertIn("status", quote)

    def test_unified_workflow_endpoint(self):
        result = self.post("/api/workflow", {
            "personas": ["学生"], "scenes": ["学习与网课"],
            "needs": ["学习资料整理"], "customer_task": "整理课程资料",
            "product": "HUAWEI MateBook 14", "generate_marketing": False,
        })
        self.assertIn("customer_insight", result)
        self.assertIn("recommendation", result)
        self.assertEqual(result["selected_product"], "HUAWEI MateBook 14")
        self.assertIsNotNone(result["quote"])

    def test_knowledge_query_and_follow_up_routes(self):
        knowledge = self.post("/api/knowledge-query", {"query":"扩展坞", "top_k":3})
        self.assertEqual(knowledge["mode"], "mock")
        self.assertIsInstance(knowledge["results"], list)
        self.assertTrue(all("source" in item and "text" in item for item in knowledge["results"]))

        plan = self.post("/api/followups/plan", {
            "start_date":"2026-10-18", "channel":"微信", "sequence":7,
        })
        self.assertEqual(len(plan["tasks"]), 4)
        self.assertEqual(plan["label"], "线索-20261018-007")
        plan["tasks"][0]["message"] = "客户提供的临时内容"
        updated = self.post("/api/followups/task", {
            "plan":plan, "task_number":1,
            "changes":{"status":"已联系", "date":"2026-10-19", "note":"已回复"},
        })
        self.assertEqual(updated["tasks"][0]["status"], "已联系")
        self.assertEqual(updated["tasks"][0]["date"], "2026-10-19")
        stopped = self.post("/api/followups/status", {"plan":updated, "status":"停止联系"})
        self.assertEqual(stopped["status"], "停止联系")

    def test_unknown_platform_returns_client_error(self):
        request = Request(self.base + "/api/marketing", data=json.dumps({"product":"MateBook 14", "platform":"Instagram"}).encode(), headers={"Content-Type":"application/json"})
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=5)
        self.assertEqual(context.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
