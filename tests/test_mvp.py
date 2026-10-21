import json
import sys
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app
from modules.pricing.pricing_module import PriceRecord, build_quote_status, compare_price_snapshots


class MvpDataTests(unittest.TestCase):
    def test_priority_concern_options_are_compact_customer_dimensions(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        choice_group = html.split('<fieldset class="choice-group">', 1)[1].split('</fieldset>', 1)[0]
        option_values = [
            fragment.split('value="', 1)[1].split('"', 1)[0]
            for fragment in choice_group.split('name="priority-concern"')[1:]
            if 'value="' in fragment
        ]
        self.assertEqual(option_values, [
            "预算与价格",
            "性能是否够用",
            "软件和外设能否使用",
            "日常使用体验",
            "售后与保障",
        ])
        for removed in ("数据安全", "竞品比较", "系统路线选择", "库存到货", "接口连接", "旧设备数据迁移"):
            self.assertNotIn(removed, option_values)

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
        self.assertTrue(all(path.startswith("P") and "\\" not in path for path in result["sources"]))
        self.assertEqual(result["evidence_fact_sources"], [result["sources"][0]] * len(result["evidence_facts"]))
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


class PriceComparisonTests(unittest.TestCase):
    @staticmethod
    def huawei_record(**changes):
        values = {
            "record_id": "HW-001",
            "product_name": "HUAWEI MateBook 14",
            "original_name": "HUAWEI MateBook 14",
            "category": "消费级PC",
            "configuration": "16GB/512GB",
            "sku": "HUAWEI-SKU-001",
            "price_type": "官方商城页面价",
            "page_price": 5899,
            "reference_price": None,
            "condition": "",
            "stock_status": "在售快照",
            "region": "中国大陆",
            "verified_at": "2026-10-17T10:00:00+08:00",
            "source_title": "华为商城 MateBook 14",
            "source_url": "https://www.vmall.com/product/matebook-14",
            "evidence": "官方商城页面价；精确 SKU",
            "verification_status": "已核验",
            "mapping_note": "",
            "processor": "Kirin X90",
            "memory_gb": 16,
            "storage_gb": 512,
            "display_size_in": 14,
            "benchmark_name": "Geekbench",
            "benchmark_version": "6.3",
            "benchmark_score": 1000,
            "benchmark_unit": "multi-core",
            "benchmark_verified": True,
            "benchmark_source_title": "公开跑分记录",
            "benchmark_source_url": "https://bench.example.test/huawei",
        }
        values.update(changes)
        return PriceRecord(**values)

    @staticmethod
    def competitor(**changes):
        values = {
            "brand": "Apple",
            "product_name": "MacBook Air 13",
            "configuration": "16GB/512GB",
            "sku": "APPLE-SKU-001",
            "category": "消费级PC",
            "price": 7999,
            "price_type": "官方商城页面价",
            "verified_at": "2026-10-17",
            "source_title": "Apple 官方商城",
            "source_url": "https://www.apple.com.cn/macbook-air/",
            "verification_status": "已核验",
            "evidence": "官方商城页面价；精确 SKU",
            "processor": "Apple silicon",
            "memory_gb": 16,
            "storage_gb": 512,
            "display_size_in": 13.6,
            "benchmark_name": "Geekbench",
            "benchmark_version": "6.3",
            "benchmark_score": 1010,
            "benchmark_unit": "multi-core",
            "benchmark_verified": True,
            "benchmark_source_title": "公开跑分记录",
            "benchmark_source_url": "https://bench.example.test/apple",
        }
        values.update(changes)
        return values

    def test_qualifying_competitor_returns_auditable_savings(self):
        huawei = self.huawei_record()
        result = compare_price_snapshots(huawei, [self.competitor()])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["savings"], 2100)
        self.assertIn("Apple", result[0]["headline"])
        self.assertEqual(result[0]["configuration_comparison"]["huawei"]["memory_gb"], 16)
        self.assertEqual(result[0]["benchmark_comparison"]["version"], "6.3")

    def test_supported_competitor_domains_are_accepted_with_the_same_evidence_gate(self):
        competitors = [
            self.competitor(brand="Samsung", product_name="Galaxy Book", source_url="https://www.samsung.com.cn/laptops/"),
            self.competitor(brand="vivo", product_name="vivo Book", source_url="https://www.vivo.com.cn/products/"),
        ]
        result = compare_price_snapshots(self.huawei_record(), competitors)
        self.assertEqual({item["competitor_brand"] for item in result}, {"Samsung", "vivo"})

    def test_quote_exposes_qualifying_comparisons(self):
        result = build_quote_status(
            "HUAWEI MateBook 14",
            records=[self.huawei_record()],
            competitor_records=[self.competitor()],
        ).to_dict()
        self.assertEqual(len(result["competitor_comparisons"]), 1)
        self.assertEqual(result["competitor_comparisons"][0]["price_difference"], 2100)

    def test_cheaper_or_equal_competitor_is_suppressed(self):
        for price in (5000, 5899):
            with self.subTest(price=price):
                self.assertEqual(compare_price_snapshots(self.huawei_record(), [self.competitor(price=price)]), [])

    def test_missing_price_or_hardware_is_suppressed(self):
        self.assertEqual(compare_price_snapshots(self.huawei_record(), [self.competitor(price=None)]), [])
        self.assertEqual(compare_price_snapshots(self.huawei_record(), [self.competitor(memory_gb=None)]), [])

    def test_missing_or_mismatched_benchmark_is_suppressed(self):
        self.assertEqual(compare_price_snapshots(self.huawei_record(), [self.competitor(benchmark_verified=False)]), [])
        self.assertEqual(compare_price_snapshots(self.huawei_record(), [self.competitor(benchmark_score=1200)]), [])

    def test_unofficial_or_untraceable_price_source_is_suppressed(self):
        self.assertEqual(compare_price_snapshots(self.huawei_record(), [self.competitor(source_url="https://shop.example.test/apple")]), [])
        self.assertEqual(compare_price_snapshots(self.huawei_record(), [self.competitor(sku="")]), [])

    def test_quote_never_maps_unknown_or_partial_input_to_a_real_price(self):
        records = [self.huawei_record()]
        for query in ("HUAWEI", "HUAWEI 量子电脑", "MateBook D 99"):
            with self.subTest(query=query):
                result = build_quote_status(query, records=records).to_dict()
                self.assertEqual(result["status"], "manual_review")
                self.assertEqual(result["product"], query)
                self.assertIsNone(result["public_price"])
                self.assertEqual(result["record_id"], "")

    def test_model_only_query_with_multiple_skus_requires_manual_review(self):
        result = build_quote_status(
            "HUAWEI MateBook 14",
            records=[
                self.huawei_record(),
                self.huawei_record(
                    record_id="HW-002",
                    configuration="32GB/1TB",
                    sku="HUAWEI-SKU-002",
                    page_price=6899,
                ),
            ],
        ).to_dict()
        self.assertEqual(result["status"], "manual_review")
        self.assertIsNone(result["public_price"])
        self.assertIn("多个型号或 SKU", result["manual_review_items"][0])


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

    def test_malformed_json_has_a_stable_client_error_contract(self):
        request = Request(
            self.base + "/api/quote",
            data=b'{"product":',
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=5)
        error = context.exception
        try:
            self.assertEqual(error.code, 400)
            self.assertEqual(json.loads(error.read().decode()), {"error": "invalid_json"})
        finally:
            error.close()

    def test_consult_marketing_and_quote_endpoints(self):
        consult = self.post("/api/consult", {"scenario":"学生学习", "product":"HUAWEI MateBook 14", "customer_task":"整理课程资料"})
        self.assertTrue(consult["scenario_questions"])
        marketing = self.post("/api/marketing", {"product":"HUAWEI MateBook 14", "platform":"小红书", "audience":"学生用户"})
        self.assertIn("title", marketing)
        quote = self.post("/api/quote", {"product":"HUAWEI MateBook 14"})
        self.assertIn("status", quote)
        script = self.post("/api/demo-script", {
            "product":"HUAWEI MateBook 14",
            "customer_task":"整理课程资料",
            "concern":"软件兼容",
        })
        self.assertEqual(script["duration_seconds"], 180)
        self.assertEqual(len(script["sections"]), 5)
        self.assertTrue(script["sections"][2]["evidence"])

    def test_customer_recommendation_endpoint_returns_models_and_evidence(self):
        result = self.post("/api/recommendation", {
            "need": "需要一台 OLED 触控屏电脑",
        })
        self.assertEqual(result["retrieval_status"], "success")
        self.assertTrue(result["recommendations"])
        recommendation = result["recommendations"][0]
        self.assertTrue(recommendation["product_name"])
        self.assertIn("fit_assessment", recommendation)
        self.assertTrue(recommendation["sources"])

    def test_recommendation_explanation_uses_customer_identity_task_and_concerns(self):
        result = self.post("/api/recommendation", {
            "need": "需要一台 OLED 触控屏电脑",
            "customer_task": "制作并演示课件",
            "customer_type": "教师",
            "usage_scenario": "备课与课堂教学",
            "priority_concerns": ["软件与外设兼容", "便携与续航"],
        })
        self.assertEqual(result["retrieval_status"], "success")
        recommendation = result["recommendations"][0]
        reason = recommendation["customer_facing_reason"]
        example = recommendation["example_scenario"]
        for expected in ("教师", "备课与课堂教学", "制作并演示课件", "软件与外设兼容", "便携与续航"):
            self.assertIn(expected, reason)
            self.assertIn(expected, example)
        self.assertIn("尚未被产品资料直接证实", reason)
        self.assertIn("结合顾客需求", result["results_markdown"])
        self.assertIn("建议现场体验", result["results_markdown"])

    def test_customer_recommendation_endpoint_keeps_unknown_need_unresolved(self):
        result = self.post("/api/recommendation", {
            "need": "需要一台适合量子编译和火星通信的电脑",
        })
        self.assertIn(result["retrieval_status"], {"no_results", "insufficient_evidence"})
        self.assertFalse(result["recommendations"])

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
        error = context.exception
        try:
            self.assertEqual(error.code, 400)
        finally:
            error.close()

    def test_bootstrap_variants_are_verified_combinations(self):
        with urlopen(self.base + "/api/bootstrap", timeout=30) as response:
            variants = json.loads(response.read().decode())["variants"]
        matebook = next(item for item in variants if item["id"] == "PRICE-0007")
        self.assertEqual(matebook["memory"], "16GB")
        self.assertEqual(matebook["storage"], "512GB")
        self.assertEqual(matebook["color"], "原野绿")
        self.assertEqual(matebook["price"], 5899)
        self.assertTrue(matebook["sku"])
        self.assertGreaterEqual(len(matebook["images"]), 3)
        self.assertTrue(all("原野绿" in item["description"] for item in matebook["images"]))
        duplicate_config = next(item for item in variants if item["id"] == "PRICE-0010")
        self.assertEqual(duplicate_config["images"], [])
        smoke_gray = next(item for item in variants if item["id"] == "PRICE-0051")
        self.assertEqual(smoke_gray["color"], "烟云灰")
        self.assertEqual(smoke_gray["images"], [])

    def test_quote_can_use_selected_verified_variant(self):
        quote = self.post("/api/quote", {"product": "unrelated", "variant_id": "PRICE-0007"})
        self.assertEqual(quote["record_id"], "PRICE-0007")
        self.assertEqual(quote["public_price"], 5899)
        self.assertIn("16GB/512GB", quote["configuration"])

    def test_product_compare_endpoint_uses_source_backed_matrix_records(self):
        with urlopen(self.base + "/api/bootstrap", timeout=5) as response:
            products = json.loads(response.read().decode())["comparison_products"]
        self.assertGreaterEqual(len(products), 2)
        self.assertTrue(all(item["source"].endswith("产品事实.md") for item in products))
        self.assertFalse(any(item["category"] == "手机" for item in products))

        result = self.post("/api/product-compare", {
            "left_product": "HUAWEI MateBook 14",
            "right_product": "HUAWEI MateBook Pro",
        })
        self.assertEqual(result["left"]["source"], "P1-产品参数库/01-鸿蒙电脑/HUAWEI MateBook 14/产品事实.md")
        self.assertEqual(result["right"]["source"], "P1-产品参数库/01-鸿蒙电脑/HUAWEI MateBook Pro/产品事实.md")
        screen = next(item for item in result["specifications"] if item["field"] == "屏幕规格")
        self.assertEqual(screen["status"], "不同")
        self.assertIn("14.2 英寸", screen["left"])
        self.assertGreater(result["difference_count"], 0)

    def test_product_compare_rejects_the_same_model(self):
        with self.assertRaises(ValueError):
            app._compare_products({
                "left_product": "HUAWEI MateBook 14",
                "right_product": "HUAWEI MateBook 14",
            })

    def test_product_compare_ui_is_served(self):
        with urlopen(self.base + "/", timeout=5) as response:
            html = response.read().decode()
        self.assertIn('data-tab="compare"', html)
        self.assertIn('id="compare-left"', html)
        self.assertIn('id="compare-right"', html)
        self.assertIn('/api/product-compare', html)


if __name__ == "__main__":
    unittest.main()
