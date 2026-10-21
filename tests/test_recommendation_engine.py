import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.recommendation.recommendation_engine import (
    _build_candidates,
    _fact_evidence,
    _finalize_facts,
    generate_recommendation_plan,
)
from modules.recommendation.retrieval_adapter import RetrievalItem, RetrievalResponse


class RecommendationEvidenceTests(unittest.TestCase):
    def test_negated_features_become_hard_exclusions_not_positive_queries(self):
        received_queries = []

        def retriever(query, *, top_k):
            received_queries.append(query)
            return RetrievalResponse(
                mode="test",
                warnings=[],
                results=[
                    RetrievalItem(
                        text="产品名称：HUAWEI MateBook 14\n屏幕：OLED 触控屏",
                        source="产品事实.md",
                        section="HUAWEI MateBook 14",
                        local_path="P1-产品参数库/01-鸿蒙电脑/HUAWEI MateBook 14/产品事实.md",
                        source_id="p1-matebook-14",
                        product_metadata={
                            "product_name": "HUAWEI MateBook 14",
                            "screen": "OLED 触控屏",
                        },
                    )
                ],
            )

        plan = generate_recommendation_plan(
            {"need": "我不想要 OLED 屏幕，也不想要触控屏"},
            retriever=retriever,
        )

        self.assertEqual(plan["customer_requirements"]["core_needs"], [])
        self.assertEqual(
            plan["customer_requirements"]["rejected_features"],
            ["OLED 屏幕", "触控屏"],
        )
        self.assertNotIn("OLED", received_queries[0])
        self.assertNotIn("触控", received_queries[0])
        self.assertFalse(plan["recommendations"])
        self.assertEqual(plan["excluded_products"][0]["product_name"], "HUAWEI MateBook 14")
        self.assertEqual(
            plan["excluded_products"][0]["fit_assessment"]["unmatched_requirements"],
            ["OLED 屏幕", "触控屏"],
        )

    def test_historical_sellpoint_is_a_snapshot_not_verified_product_evidence(self):
        response = RetrievalResponse(
            mode="test",
            warnings=[],
            results=[
                RetrievalItem(
                    text="| HUAWEI MateBook 14 | OLED 触控屏 | 历史专区归类 |",
                    source="历史专区快照.md",
                    local_path="P6-营销素材库/历史专区快照.md",
                    source_id="p6-history",
                )
            ],
        )

        candidates, _ = _build_candidates(response)
        self.assertEqual(len(candidates), 1)
        facts = _finalize_facts(next(iter(candidates.values())))

        self.assertEqual(facts[0]["field"], "专区公开卖点（历史快照）")
        self.assertEqual(facts[0]["status"], "snapshot")
        self.assertEqual(_fact_evidence(facts), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
