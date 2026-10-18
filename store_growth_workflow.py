"""Integration layer for recommendation, pricing, marketing, and compliance."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Mapping

BASE = Path(__file__).resolve().parent
KB = BASE / "knowledge-base" / "华为PC全板块深度知识库_v7"
TEAM_DIR = BASE / "3号(1)"
COMPLIANCE_DIR = BASE / "BLOCK-07"

# Preserve the independent teammate modules and their import contracts.
for module_dir in (str(TEAM_DIR), str(COMPLIANCE_DIR)):
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
os.environ.setdefault("KB_ROOT", str(KB))

from customer_insight_agent.kb_agent import KnowledgeBase, build_insight  # noqa: E402
from recommendation_engine import (  # noqa: E402
    generate_recommendation_plan,
    render_customer_requirements,
    render_recommendation_results,
)
from block07_compliance import build_evidence_section  # noqa: E402
from marketing_content_module import generate_marketing_content  # noqa: E402
from pricing_module import build_quote_status  # noqa: E402


_INSIGHT_KB: KnowledgeBase | None = None


def run_customer_insight(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Build the first-stage insight card from explicit customer input."""
    global _INSIGHT_KB
    if _INSIGHT_KB is None:
        os.environ.setdefault("HUAWEI_PC_KB", str(KB))
        _INSIGHT_KB = KnowledgeBase(KB)
    return build_insight(dict(payload), _INSIGHT_KB)


def run_customer_recommendation(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Generate a standalone model recommendation from customer needs."""
    if not isinstance(payload, Mapping):
        raise TypeError("recommendation payload must be an object")

    hard_conditions = payload.get("hard_conditions", "")
    if isinstance(hard_conditions, list):
        hard_text = "\n".join(str(item).strip() for item in hard_conditions if str(item).strip())
    else:
        hard_text = str(hard_conditions or "").strip()
    for extra in (payload.get("required_software"), payload.get("peripherals")):
        if extra and str(extra).strip():
            hard_text = "\n".join(filter(None, (hard_text, str(extra).strip())))

    profile = {
        "need": str(payload.get("need") or payload.get("customer_task") or "").strip(),
        "customer_type": str(payload.get("customer_type") or payload.get("persona") or "").strip(),
        "usage_scenario": str(payload.get("usage_scenario") or payload.get("scenario") or "").strip(),
        "budget_text": str(payload.get("budget_text") or payload.get("budget") or "").strip(),
        "hard_conditions": hard_text,
        "preferences": str(payload.get("preferences") or payload.get("concern") or "").strip(),
        "rejected_features": str(payload.get("rejected_features") or "").strip(),
        "notes": str(payload.get("notes") or "").strip(),
    }
    plan = generate_recommendation_plan(profile)
    return {
        "profile": profile,
        "retrieval_status": plan.get("retrieval_status"),
        "recommendations": plan.get("recommendations", []),
        "unresolved_candidates": plan.get("unresolved_candidates", []),
        "excluded_products": plan.get("excluded_products", []),
        "warnings": plan.get("warnings", []),
        "sources": plan.get("sources", []),
        "plan": plan,
        "requirements_markdown": render_customer_requirements(plan),
        "results_markdown": render_recommendation_results(plan),
    }


def _marketing_evidence(result: Mapping[str, Any]) -> list[dict[str, str]]:
    sources = [str(item) for item in result.get("sources", [])]
    facts = []
    for index, claim in enumerate(result.get("evidence_facts", []), start=1):
        facts.append({
            "id": f"F{index}",
            "claim": str(claim),
            "source_title": Path(sources[0]).name if sources else "",
            "source_path": sources[0] if sources else "",
        })
    return facts


def _marketing_images(result: Mapping[str, Any]) -> list[dict[str, str]]:
    product = str(result.get("product", ""))
    images = []
    for index, image in enumerate(result.get("recommended_images", []), start=1):
        images.append({
            "id": f"I{index}",
            "name": str(image.get("name", "")),
            "title": str(image.get("description", "")),
            "url": str(image.get("image_url", "")),
            "model": product,
            "position_hint": str(image.get("usage_note", "")),
        })
    return images


def run_store_growth_workflow(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Run one evidence-first customer journey and return each auditable stage."""
    if not isinstance(payload, Mapping):
        raise TypeError("workflow payload must be an object")

    insight = run_customer_insight(payload)
    customer = insight.get("customer", {})
    insight_need = customer.get("needs", {}).get("value", "")
    insight_scene = customer.get("scene", {}).get("value", "")
    insight_persona = customer.get("persona", {}).get("value", "")
    insight_concern = customer.get("concern", {}).get("value", "")
    profile = {
        "need": str(payload.get("customer_task") or payload.get("need") or insight_need).strip(),
        "customer_type": str(payload.get("customer_type") or insight_persona),
        "usage_scenario": str(payload.get("scenario") or payload.get("usage_scenario") or insight_scene),
        "budget_text": str(payload.get("budget") or payload.get("budget_text") or ""),
        "hard_conditions": "\n".join(str(x) for x in payload.get("hard_conditions", []) if x)
        if isinstance(payload.get("hard_conditions"), list)
        else "\n".join(filter(None, (
            str(payload.get("hard_conditions", "")),
            str(payload.get("required_software", "")),
            str(payload.get("peripherals", "")),
        ))),
        "preferences": str(payload.get("preferences") or insight_concern),
        "rejected_features": str(payload.get("rejected_features", "")),
        "notes": "\n".join(filter(None, (
            str(payload.get("required_software", "")),
            str(payload.get("peripherals", "")),
            str(payload.get("notes", "")),
        ))),
    }
    recommendation = generate_recommendation_plan(profile)
    recommended = recommendation.get("recommendations", [])
    explicit_product = str(payload.get("product", "")).strip()
    product = explicit_product or (
        str(recommended[0].get("product_name", "")) if recommended else ""
    )

    quote = build_quote_status(product).to_dict() if product else None
    marketing = None
    compliance = None
    if product and payload.get("generate_marketing", True):
        marketing = generate_marketing_content(
            product,
            str(payload.get("platform", "小红书")),
            str(payload.get("audience", "门店顾客")),
            str(payload.get("goal", "引导咨询")),
            str(payload.get("scenario", "")),
            knowledge_base_dir=KB,
        )
        compliance = build_evidence_section(
            facts=_marketing_evidence(marketing),
            images=_marketing_images(marketing),
            copy={
                "title": str(marketing.get("title", "")),
                "body": str(marketing.get("body", "")),
                "cta": str(marketing.get("call_to_action", "")),
            },
            product=product,
            extra_pending=list(marketing.get("warnings", [])),
        )
        marketing["compliance_review"] = compliance

    return {
        "workflow": "store_growth_evidence_first_v1",
        "customer_insight": insight,
        "selected_product": product or None,
        "product_selection_basis": "user_selected" if explicit_product else (
            "top_evidence_supported_recommendation" if product else "none"
        ),
        "recommendation": {
            "plan": recommendation,
            "requirements_markdown": render_customer_requirements(recommendation),
            "results_markdown": render_recommendation_results(recommendation),
        },
        "quote": quote,
        "marketing": marketing,
        "compliance": compliance,
        "guardrails": [
            "推荐仅基于检索来源；硬条件未知时不会按满足处理。",
            "价格为来源快照，不代表当前成交价、库存或促销。",
            "软件与外设兼容性必须在目标版本和环境验证。",
            "营销内容仅为草稿；合规通过也不替代人工发布审核。",
        ],
    }
