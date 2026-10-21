"""Deterministic, source-grounded product recommendation for the offline demo.

No language model, online search, or product catalog is synthesized here. Product
candidates and facts are extracted only from the configured retriever's response.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from .retrieval_adapter import RetrievalAdapterError, RetrievalResponse, retrieve_with_adapter

LOGGER = logging.getLogger(__name__)
MAX_RECOMMENDATIONS = 3
RETRIEVAL_TOP_K = 20
MAX_INPUT_LENGTH = 4000

_PRODUCT_PATTERN = re.compile(
    r"(?i)(?:HUAWEI\s+)?MateBook\s+(?:Pro\s+S|Pro|Fold|14|X\s*Pro(?:\s+Premium\s+Edition)?|B\d{1,3}|D\d{1,3}|E\d{1,3}|\d{2})"
    r"(?:\s+(?:非凡大师|鸿蒙版|麒麟\s+X90(?:\s+Plus)?))*"
)
_TABLE_ROW_PATTERN = re.compile(r"\|\s*([^|\n]{2,100}?)\s*\|\s*([^|\n]{1,500}?)\s*\|\s*([^|\n]{1,300}?)\s*\|")
_ASCII_TOKEN_PATTERN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")

_FACT_ALIASES: dict[str, tuple[str, ...]] = {
    "型号": ("型号", "model", "product_model"),
    "产品类别": ("产品类别", "类别", "category", "product_category"),
    "主要功能": ("主要功能", "功能", "features", "functions", "key_features"),
    "处理器": ("处理器", "CPU", "processor"),
    "内存": ("内存", "RAM", "memory"),
    "存储": ("存储", "硬盘", "storage"),
    "操作系统": ("操作系统", "系统", "OS", "operating_system"),
    "屏幕": ("屏幕", "显示屏", "display", "screen"),
    "电池": ("电池", "battery"),
    "重量": ("重量", "weight"),
    "价格": ("价格", "售价", "price"),
    "币种": ("币种", "currency"),
    "适用场景": ("适用场景", "场景", "scenarios", "use_cases"),
    "兼容性": ("兼容性", "compatibility", "compatible_with"),
    "使用限制": ("使用限制", "限制", "limitations", "restrictions"),
    "保修": ("保修", "质保", "warranty"),
    "服务": ("服务", "service", "support"),
    "交付": ("交付", "delivery"),
}
_METADATA_ID_KEYS = ("product_id", "id", "sku", "sbom_code", "product_code")
_METADATA_NAME_KEYS = ("product_name", "product_title", "name")
_METADATA_FACT_KEYS = {
    alias.lower(): field_name
    for field_name, aliases in _FACT_ALIASES.items()
    for alias in aliases
}
_HARD_CUES = (
    "必须",
    "必需",
    "硬性",
    "不能少于",
    "不低于",
    "至少",
    "不得超过",
    "不能超过",
    "不超过",
    "不高于",
    "必须支持",
)
_REJECT_CUES = ("不想要", "不接受", "拒绝", "不能要", "不需要", "不要", "避免")
_NEGATIVE_FACT_PATTERN = re.compile(
    r"(?:不支持|不适用|不兼容|无法|不含|不提供|没有|无|需另购|需单独购买|不包含)"
)
_GENERIC_TERMS = {
    "需要", "希望", "适合", "产品", "电脑", "客户", "购买", "使用", "支持",
    "功能", "要求", "满足", "最好", "可以", "一个", "能够", "作为", "进行",
}
_SYNONYM_GROUPS = (
    {"触控", "触屏", "触摸屏", "触摸"},
    {"轻薄", "轻便", "便携"},
    {"长续航", "续航", "电池续航"},
)


@dataclass(frozen=True)
class CustomerProfile:
    need: str
    customer_type: str = ""
    usage_scenario: str = ""
    budget_text: str = ""
    hard_conditions: str = ""
    preferences: str = ""
    rejected_features: str = ""
    notes: str = ""
    customer_task: str = ""

    @classmethod
    def from_values(cls, values: Mapping[str, Any]) -> "CustomerProfile":
        cleaned: dict[str, str] = {}
        limits = {
            "need": MAX_INPUT_LENGTH,
            "customer_task": 1000,
            "customer_type": 300,
            "usage_scenario": 1000,
            "budget_text": 300,
            "hard_conditions": 1200,
            "preferences": 1200,
            "rejected_features": 1200,
            "notes": 1200,
        }
        for name, limit in limits.items():
            value = values.get(name, "")
            if value is None:
                value = ""
            if not isinstance(value, str):
                raise ValueError(f"{name} 必须是文本。")
            value = value.strip()
            if len(value) > limit:
                raise ValueError(f"{name} 内容过长，请控制在 {limit} 个字符以内。")
            cleaned[name] = value
        if not cleaned["need"]:
            raise ValueError("请填写客户需求描述后再生成方案。")
        return cls(**cleaned)

    def explicit_fields(self) -> dict[str, str]:
        return {
            "客户需求描述": self.need,
            "首要任务": self.customer_task,
            "客户类型": self.customer_type,
            "使用场景": self.usage_scenario,
            "预算范围": self.budget_text,
            "必须满足的条件": self.hard_conditions,
            "偏好或加分项": self.preferences,
            "不接受的产品特征": self.rejected_features,
            "其他补充信息": self.notes,
        }

    def retrieval_query(self) -> str:
        # Exclusions constrain ranking; they must not act as positive retrieval terms.
        return " ".join(value for value in (
            _strip_rejected_clauses(self.need),
            _strip_rejected_clauses(self.customer_task),
            self.customer_type,
            self.usage_scenario,
            self.budget_text,
            self.hard_conditions,
            self.preferences,
            self.notes,
        ) if value)


@dataclass(frozen=True)
class RequirementSet:
    core_needs: list[str]
    hard_constraints: list[str]
    preferences: list[str]
    rejected_features: list[str]
    budget: dict[str, Any] | None
    usage_scenarios: list[str]
    unknowns: list[str]
    inferred_preferences: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "core_needs": self.core_needs,
            "hard_constraints": self.hard_constraints,
            "preferences": self.preferences,
            "rejected_features": self.rejected_features,
            "budget": self.budget,
            "usage_scenarios": self.usage_scenarios,
            "unknowns": self.unknowns,
            "inferred_preferences": self.inferred_preferences,
        }


@dataclass(frozen=True)
class SourceReference:
    id: str
    original_source_id: str | None
    title: str
    url: str | None
    local_path: str | None
    page: str | int | None
    section: str | None
    line_start: int | None
    line_end: int | None
    demo: bool
    traceable: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "original_source_id": self.original_source_id,
            "title": self.title,
            "url": self.url,
            "local_path": self.local_path,
            "page": self.page,
            "section": self.section,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "demo": self.demo,
            "traceable": self.traceable,
        }


@dataclass
class _Candidate:
    name: str
    product_id: str | None = None
    model: str | None = None
    raw_facts: list[dict[str, Any]] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _RequirementCheck:
    text: str
    status: str
    fact: dict[str, Any] | None = None


def _split_items(text: str) -> list[str]:
    items: list[str] = []
    for line in re.split(r"[\r\n;；]+", text):
        item = re.sub(r"^\s*[-*•\d.、]+\s*", "", line).strip()
        if item and item not in items:
            items.append(item)
    return items


def _split_needs(text: str) -> list[str]:
    parts: list[str] = []
    for sentence in re.split(r"[。！？!?;；,，\r\n]+", text):
        sentence = sentence.strip(" ，,、\t")
        if sentence and sentence not in parts:
            parts.append(sentence)
    return parts


def _extract_rejected(text: str) -> list[str]:
    """Extract every separately stated exclusion without retaining conjunctions."""
    rejected: list[str] = []
    cues = "|".join(re.escape(cue) for cue in sorted(_REJECT_CUES, key=len, reverse=True))
    cue_pattern = re.compile(cues)
    for sentence in _split_needs(text):
        matches = list(cue_pattern.finditer(sentence))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(sentence)
            feature = sentence[match.end() : end]
            feature = re.sub(r"^[\s：:,，、]*(?:也|都)?", "", feature)
            feature = re.sub(r"[\s：:,，、]*(?:也|都)?$", "", feature).strip()
            # "不想要 OLED 和触控屏" is two independent exclusions too.
            for item in re.split(r"(?:、|和|及|以及)", feature):
                item = item.strip(" ：:，,、 ")
                if item and item not in rejected:
                    rejected.append(item)
    return rejected


def _strip_rejected_clauses(text: str) -> str:
    """Keep the affirmative part of a need; exclusions are assessed separately."""
    kept: list[str] = []
    for sentence in _split_needs(text):
        positions = [
            sentence.find(cue) for cue in _REJECT_CUES
            if sentence.find(cue) >= 0
        ]
        if not positions:
            kept.append(sentence)
            continue
        affirmative = sentence[:min(positions)].rstrip(" ，,、；;但也").strip()
        # A speaker prefix (for example, "我不想要…") is not a positive need.
        if affirmative and affirmative not in {"我", "我们", "客户", "顾客", "用户", "也", "都"}:
            kept.append(affirmative)
    return "；".join(kept)


def _parse_budget(text: str) -> tuple[dict[str, Any] | None, str | None]:
    if not text.strip():
        return None, None
    currency = None
    for pattern, code in (
        (r"CNY|RMB|人民币|人民币元|元|¥|￥", "CNY"),
        (r"USD|美元|US\$|\$", "USD"),
        (r"EUR|欧元|€", "EUR"),
    ):
        if re.search(pattern, text, re.IGNORECASE):
            currency = code
            break

    number_pattern = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(万)?")
    values: list[float] = []
    for match in number_pattern.finditer(text):
        try:
            number = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if match.group(2):
            number *= 10000
        values.append(number)
    if not values:
        return None, "预算无法解析为金额；请用数字补充金额和币种，例如 8000-10000 元。"
    if not currency:
        return {
            "raw": text,
            "minimum": min(values) if len(values) > 1 else 0,
            "maximum": max(values),
            "currency": None,
        }, "预算未注明币种或单位，暂不能执行价格匹配。"
    lower_cues = ("至少", "不低于", "最低")
    upper_cues = ("以内", "不超过", "不得超过", "最高", "预算上限")
    if len(values) == 1:
        minimum = values[0] if any(cue in text for cue in lower_cues) else 0
        maximum = None if minimum else values[0]
    else:
        minimum, maximum = min(values), max(values)
    if len(values) > 1 and values[0] > values[1] and re.search(r"[-~～至到]", text):
        return {"raw": text, "minimum": values[0], "maximum": values[1], "currency": currency}, "预算下限大于上限，条件互相矛盾。"
    return {
        "raw": text,
        "minimum": minimum,
        "maximum": maximum,
        "currency": currency,
    }, None


def _extract_budget(profile: CustomerProfile) -> tuple[dict[str, Any] | None, str | None, str]:
    if profile.budget_text:
        budget, issue = _parse_budget(profile.budget_text)
        return budget, issue, profile.budget_text
    match = re.search(r"预算[^。！？!?;；\r\n]{0,35}", profile.need)
    if not match:
        return None, None, ""
    extracted = match.group(0)
    budget, issue = _parse_budget(extracted)
    return budget, issue, extracted


def _canonical_terms(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", text.lower())
    terms = {token.lower() for token in _ASCII_TOKEN_PATTERN.findall(text)}
    chars = _CJK_PATTERN.findall(compact)
    terms.update(chars[index] + chars[index + 1] for index in range(len(chars) - 1))
    terms = {term for term in terms if term not in _GENERIC_TERMS and len(term) > 1}
    for group in _SYNONYM_GROUPS:
        if group.intersection(terms) or any(term in compact for term in group):
            terms.update(group)
    return terms


def _overlap_status(requirement: str, evidence: str) -> bool:
    compact_requirement = re.sub(r"[\s，。；：:,.!?！？、]+", "", requirement.lower())
    compact_evidence = re.sub(r"[\s，。；：:,.!?！？、]+", "", evidence.lower())
    if compact_requirement and compact_requirement in compact_evidence:
        return True
    required_terms = _canonical_terms(requirement)
    evidence_terms = _canonical_terms(evidence)
    if not required_terms or not evidence_terms:
        return False
    shared = required_terms & evidence_terms
    return len(shared) >= max(1, math.ceil(len(required_terms) * 0.35))


def _values_to_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        return "；".join(str(part).strip() for part in value if str(part).strip())
    if isinstance(value, Mapping):
        return "；".join(f"{key}：{part}" for key, part in value.items())
    return "" if value is None else str(value).strip()


def _extract_product_names(text: str) -> list[str]:
    names: list[str] = []
    for match in _PRODUCT_PATTERN.finditer(text):
        name = re.sub(r"\s+", " ", match.group(0)).strip()
        if name and name.casefold() not in {item.casefold() for item in names}:
            names.append(name)
    return names


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
        return value.strip()
    return None


def _source_reference(item: Any, index: int) -> SourceReference:
    title = str(getattr(item, "source", "") or "来源未提供").strip()
    local_path = getattr(item, "local_path", None)
    url = _safe_url(getattr(item, "url", None))
    traceable = bool(title and title != "来源未提供") or bool(local_path) or bool(url)
    raw_source_id = getattr(item, "source_id", None)
    return SourceReference(
        id=f"source-{index}",
        original_source_id=str(raw_source_id) if raw_source_id not in (None, "") else None,
        title=title or "来源未提供",
        url=url,
        local_path=str(local_path) if local_path else None,
        page=getattr(item, "page", None),
        section=getattr(item, "section", None),
        line_start=getattr(item, "line_start", None),
        line_end=getattr(item, "line_end", None),
        demo=bool(getattr(item, "demo", False)),
        traceable=traceable,
    )


def _metadata(item: Any) -> Mapping[str, Any]:
    value = getattr(item, "product_metadata", {})
    return value if isinstance(value, Mapping) else {}


def _metadata_value(metadata: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in metadata and metadata[key] not in (None, ""):
            return metadata[key]
    return None


def _candidate_key(name: str, product_id: str | None) -> str:
    return f"{name.casefold()}::{product_id or ''}"


def _ensure_candidate(
    candidates: dict[str, _Candidate],
    name: str,
    product_id: str | None,
    model: str | None,
) -> _Candidate:
    key = _candidate_key(name, product_id)
    candidate = candidates.get(key)
    if candidate is None:
        candidate = _Candidate(name=name, product_id=product_id, model=model)
        candidates[key] = candidate
    elif candidate.model is None and model:
        candidate.model = model
    return candidate


def _is_p1_product_fact_source(source: SourceReference) -> bool:
    path = (source.local_path or "").replace("\\", "/")
    return "P1-产品参数库/" in path and path.endswith("/产品事实.md")


def _add_fact(
    candidate: _Candidate,
    field_name: str,
    value: Any,
    source: SourceReference,
    evidence_kind: str = "unverified",
) -> None:
    text = _values_to_text(value)
    if not text:
        return
    candidate.raw_facts.append(
        {
            "field": field_name,
            "value": text,
            "source_ids": [source.id],
            "traceable": source.traceable,
            "evidence_kinds": [evidence_kind],
        }
    )
    if source.id not in candidate.source_ids:
        candidate.source_ids.append(source.id)


def _parse_text_facts(text: str) -> list[tuple[str, str]]:
    aliases = sorted(
        {alias for values in _FACT_ALIASES.values() for alias in values},
        key=len,
        reverse=True,
    )
    known = "|".join(re.escape(alias) for alias in aliases)
    generic = r"[\u3400-\u4dbf\u4e00-\u9fffA-Za-z][\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9_ /-]{0,24}"
    pattern = re.compile(
        rf"(?:(?P<known>{known})|(?:^|[\r\n]|\s-\s|-\s*|[•])(?P<generic>{generic}))\s*[:：]\s*",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(text))
    facts: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = text[match.end() : end].strip(" \t\r\n-|•;；,，")
        value = re.sub(r"\s+-\s*$", "", value).strip()
        if not value:
            continue
        alias = (match.group("known") or match.group("generic")).lower().strip()
        field_name = _METADATA_FACT_KEYS.get(alias)
        if not field_name:
            continue
        if len(value) > 260:
            value = value[:259].rstrip() + "…"
        facts.append((field_name, value))
    return facts


def _metadata_facts(metadata: Mapping[str, Any]) -> list[tuple[str, Any]]:
    facts: list[tuple[str, Any]] = []
    for key, value in metadata.items():
        field_name = _METADATA_FACT_KEYS.get(str(key).lower())
        if field_name:
            facts.append((field_name, value))
        elif str(key).lower() in {"specifications", "specs", "attributes", "facts"} and isinstance(value, Mapping):
            for nested_key, nested_value in value.items():
                nested_field = _METADATA_FACT_KEYS.get(str(nested_key).lower(), str(nested_key))
                facts.append((nested_field, nested_value))
    return facts


def _build_candidates(
    response: RetrievalResponse,
) -> tuple[dict[str, _Candidate], list[SourceReference]]:
    candidates: dict[str, _Candidate] = {}
    sources: list[SourceReference] = []
    for index, item in enumerate(response.results, start=1):
        source = _source_reference(item, index)
        sources.append(source)
        text = str(getattr(item, "text", "") or "")
        section = str(getattr(item, "section", "") or "")
        source_title = str(getattr(item, "source", "") or "")
        metadata = _metadata(item)
        metadata_name_value = _metadata_value(metadata, _METADATA_NAME_KEYS)
        metadata_name = _values_to_text(metadata_name_value) if metadata_name_value is not None else ""
        product_id_value = _metadata_value(metadata, _METADATA_ID_KEYS)
        product_id = _values_to_text(product_id_value) if product_id_value is not None else None
        model_value = _metadata_value(metadata, ("model", "product_model", "型号"))
        model = _values_to_text(model_value) if model_value is not None else None

        names: list[str] = []
        if metadata_name:
            names.append(metadata_name)
        for name in _extract_product_names(" ".join((text, section, source_title))):
            if name.casefold() not in {existing.casefold() for existing in names}:
                names.append(name)

        row_matches = list(_TABLE_ROW_PATTERN.finditer(text))
        row_product_names: set[str] = set()
        for row in row_matches:
            first_cell = row.group(1).strip().strip("*` ")
            row_names = _extract_product_names(first_cell)
            if not row_names:
                continue
            row_name = row_names[0]
            row_product_names.add(row_name.casefold())
            candidate = _ensure_candidate(candidates, row_name, None, None)
            sellpoint = row.group(2).strip()
            classification = row.group(3).strip()
            _add_fact(
                candidate, "专区公开卖点（历史快照）", sellpoint, source,
                evidence_kind="snapshot",
            )
            if classification:
                _add_fact(
                    candidate, "知识库归类说明（非产品参数）", classification, source,
                    evidence_kind="context",
                )

        for name in names:
            candidate = _ensure_candidate(candidates, name, product_id, model)
            if source.id not in candidate.source_ids:
                candidate.source_ids.append(source.id)
            evidence_kind = "official_spec" if _is_p1_product_fact_source(source) else "unverified"
            if metadata_name and name.casefold() == metadata_name.casefold():
                for field_name, value in _metadata_facts(metadata):
                    _add_fact(candidate, field_name, value, source, evidence_kind=evidence_kind)
            names_in_text = _extract_product_names(text)
            is_source_specific = name.casefold() in {
                value.casefold() for value in _extract_product_names(section + " " + source_title)
            }
            if name.casefold() in row_product_names:
                continue
            is_metadata_bound_product_fact = (
                bool(metadata_name)
                and name.casefold() == metadata_name.casefold()
                and _is_p1_product_fact_source(source)
            )
            if is_source_specific or is_metadata_bound_product_fact or len(names_in_text) == 1:
                parsed_facts = _parse_text_facts(text)
                section_field = _METADATA_FACT_KEYS.get(section.lower().strip())
                if is_metadata_bound_product_fact and section_field:
                    parsed_facts.append((section_field, text))
                for field_name, value in parsed_facts:
                    _add_fact(candidate, field_name, value, source, evidence_kind=evidence_kind)

    return candidates, sources


def _finalize_facts(candidate: _Candidate) -> list[dict[str, Any]]:
    by_field: dict[str, dict[str, dict[str, Any]]] = {}
    for fact in candidate.raw_facts:
        field_name = fact["field"]
        normalized_value = re.sub(r"\s+", " ", fact["value"]).strip().casefold()
        values = by_field.setdefault(field_name, {})
        existing = values.get(normalized_value)
        if existing is None:
            values[normalized_value] = {
                "field": field_name,
                "value": fact["value"],
                "source_ids": list(fact["source_ids"]),
                "traceable": bool(fact["traceable"]),
                "evidence_kinds": list(fact.get("evidence_kinds", ["unverified"])),
            }
        else:
            existing["source_ids"] = sorted(set(existing["source_ids"] + fact["source_ids"]))
            existing["traceable"] = existing["traceable"] or bool(fact["traceable"])
            existing["evidence_kinds"] = sorted(set(
                existing["evidence_kinds"] + fact.get("evidence_kinds", ["unverified"])
            ))

    finalized: list[dict[str, Any]] = []
    for values in by_field.values():
        distinct = list(values.values())
        if len(distinct) == 1:
            kinds = set(distinct[0].get("evidence_kinds", ()))
            if distinct[0]["traceable"] and "official_spec" in kinds:
                distinct[0]["status"] = "verified"
            elif kinds == {"snapshot"}:
                distinct[0]["status"] = "snapshot"
            else:
                distinct[0]["status"] = "unverified"
            finalized.append(distinct[0])
            continue
        all_sources = sorted({source_id for fact in distinct for source_id in fact["source_ids"]})
        finalized.append(
            {
                "field": distinct[0]["field"],
                "value": "来源冲突，未选择单一值",
                "source_ids": all_sources,
                "traceable": any(fact["traceable"] for fact in distinct),
                "status": "conflict",
                "conflicting_values": [
                    {"value": fact["value"], "source_ids": fact["source_ids"]}
                    for fact in distinct
                ],
            }
        )
    return finalized


def _fact_evidence(facts: list[dict[str, Any]], *, include_historical_claims: bool = False) -> str:
    excluded_fields = {"知识库归类说明（非产品参数）"}
    if not include_historical_claims:
        excluded_fields.add("专区公开卖点（历史快照）")
    return " ".join(
        f"{fact['field']} {fact['value']}"
        for fact in facts
        if fact.get("status") == "verified"
        and fact.get("traceable")
        and fact.get("field") not in excluded_fields
    )


def _negative_evidence(requirement: str, evidence: str) -> bool:
    terms = sorted(_canonical_terms(requirement), key=len, reverse=True)
    for term in terms:
        if len(term) >= 2:
            pattern = re.compile(
                rf"(?:{_NEGATIVE_FACT_PATTERN.pattern}).{{0,12}}{re.escape(term)}|"
                rf"{re.escape(term)}.{{0,12}}(?:{_NEGATIVE_FACT_PATTERN.pattern})",
                re.IGNORECASE,
            )
            if pattern.search(evidence):
                return True
    return False


def _check_requirement(requirement: str, evidence: str, *, hard: bool) -> _RequirementCheck:
    if not evidence.strip():
        return _RequirementCheck(requirement, "unknown")
    if hard and _negative_evidence(requirement, evidence):
        return _RequirementCheck(requirement, "mismatch")
    if _overlap_status(requirement, evidence):
        return _RequirementCheck(requirement, "matched")
    return _RequirementCheck(requirement, "unknown")


def _extract_rejected_term(text: str) -> str:
    for cue in _REJECT_CUES:
        index = text.find(cue)
        if index >= 0:
            return text[index + len(cue) :].strip(" ：:，,、 ")
    return text


def _price_from_facts(facts: list[dict[str, Any]]) -> tuple[float | None, str | None]:
    price_fact = next(
        (fact for fact in facts if fact["field"] in {"价格", "price"} and fact.get("status") != "conflict"),
        None,
    )
    if not price_fact:
        return None, None
    value = price_fact["value"]
    budget, _ = _parse_budget(value)
    if not budget or budget.get("maximum") is None:
        return None, None
    return float(budget["maximum"]), budget.get("currency")


def _check_budget(budget: dict[str, Any] | None, facts: list[dict[str, Any]]) -> _RequirementCheck | None:
    if not budget:
        return None
    price, currency = _price_from_facts(facts)
    if price is None or currency is None or budget.get("currency") is None:
        return _RequirementCheck(f"预算范围：{budget['raw']}", "unknown")
    if currency != budget["currency"]:
        return _RequirementCheck(f"预算范围：{budget['raw']}", "unknown")
    minimum = float(budget.get("minimum") or 0)
    maximum = budget.get("maximum")
    if price < minimum or (maximum is not None and price > float(maximum)):
        return _RequirementCheck(f"预算范围：{budget['raw']}", "mismatch")
    fact = next(fact for fact in facts if fact["field"] in {"价格", "price"} and fact.get("status") != "conflict")
    return _RequirementCheck(f"预算范围：{budget['raw']}", "matched", fact)


def _profile_and_requirements(profile: CustomerProfile) -> tuple[RequirementSet, list[str], str | None]:
    core_needs = _split_needs(_strip_rejected_clauses(
        "\n".join(value for value in (profile.customer_task, profile.need) if value)
    ))
    explicit_hard = _split_items(profile.hard_conditions)
    detected_hard: list[str] = []
    for sentence in core_needs:
        for cue in sorted(_HARD_CUES, key=len, reverse=True):
            index = sentence.find(cue)
            if index >= 0:
                clause = sentence[index + len(cue) :].strip(" ：:，,、 ") or sentence
                detected_hard.append(clause)
                break
    hard_constraints = list(dict.fromkeys(explicit_hard + detected_hard))
    preferences = _split_items(profile.preferences)
    rejected = list(dict.fromkeys(_split_items(profile.rejected_features) + _extract_rejected(profile.need)))
    budget_text = profile.budget_text
    budget, budget_issue, used_budget_text = _extract_budget(profile)
    if used_budget_text and not budget_text:
        hard_constraints.append(f"预算限制：{used_budget_text}")
    for condition in hard_constraints:
        if any(_overlap_status(_extract_rejected_term(item), condition) for item in rejected):
            return (
                RequirementSet(core_needs, hard_constraints, preferences, rejected, budget, _split_items(profile.usage_scenario), [], []),
                ["同一产品特征同时出现在必须满足条件和不接受特征中，请修改后重试。"],
                "客户条件存在明显冲突。",
            )
    if budget_issue and "互相矛盾" in budget_issue:
        return (
            RequirementSet(core_needs, hard_constraints, preferences, rejected, budget, _split_items(profile.usage_scenario), [], []),
            [budget_issue],
            "预算范围存在矛盾，请重新填写。",
        )
    unknowns: list[str] = []
    if not profile.customer_type:
        unknowns.append("客户类型未提供")
    if not profile.usage_scenario:
        unknowns.append("具体使用场景未提供")
    if not budget:
        unknowns.append("预算未提供，系统不会猜测")
    elif budget_issue:
        unknowns.append(budget_issue)
    if not profile.hard_conditions:
        unknowns.append("未单独填写硬性条件；仅识别需求描述中明确使用硬性词语的句子")
    requirements = RequirementSet(
        core_needs=core_needs,
        hard_constraints=hard_constraints,
        preferences=preferences,
        rejected_features=rejected,
        budget=budget,
        usage_scenarios=_split_items(profile.usage_scenario),
        unknowns=unknowns,
    )
    warnings = [budget_issue] if budget_issue else []
    if not profile.customer_type:
        warnings.append("未填写客户类型；不会据此推断购买偏好。")
    return requirements, warnings, None


def _assess_candidate(
    candidate: _Candidate,
    requirements: RequirementSet,
    sources_by_id: Mapping[str, SourceReference],
) -> dict[str, Any]:
    facts = _finalize_facts(candidate)
    evidence = _fact_evidence(facts)
    hard_evidence = _fact_evidence(facts, include_historical_claims=False)
    core_checks = [_check_requirement(need, evidence, hard=False) for need in requirements.core_needs]
    hard_checks = [_check_requirement(condition, hard_evidence, hard=True) for condition in requirements.hard_constraints]
    rejected_checks: list[_RequirementCheck] = []
    for rejected in requirements.rejected_features:
        feature = _extract_rejected_term(rejected)
        if not hard_evidence:
            rejected_checks.append(_RequirementCheck(rejected, "unknown"))
        elif _negative_evidence(feature, hard_evidence):
            rejected_checks.append(_RequirementCheck(rejected, "matched"))
        elif _overlap_status(feature, hard_evidence):
            rejected_checks.append(_RequirementCheck(rejected, "mismatch"))
        else:
            rejected_checks.append(_RequirementCheck(rejected, "unknown"))
    budget_check = _check_budget(requirements.budget, facts)
    if budget_check:
        hard_checks.append(budget_check)

    scene_checks = [_check_requirement(scene, evidence, hard=False) for scene in requirements.usage_scenarios]
    preference_checks = [_check_requirement(item, evidence, hard=False) for item in requirements.preferences]
    hard_checks.extend(rejected_checks)
    hard_mismatches = [check for check in hard_checks if check.status == "mismatch"]
    hard_unknowns = [check for check in hard_checks if check.status == "unknown"]
    core_matches = [check for check in core_checks if check.status == "matched"]
    core_unknowns = [check for check in core_checks if check.status == "unknown"]
    all_sources = [sources_by_id[source_id] for source_id in candidate.source_ids if source_id in sources_by_id]
    has_traceable_source = any(source.traceable for source in all_sources)
    has_supported_need = bool(core_matches or any(check.status == "matched" for check in scene_checks))

    if hard_mismatches:
        level = "适配度较低"
    elif not has_traceable_source or not evidence or hard_unknowns or not has_supported_need:
        level = "信息不足，暂无法判断"
    elif core_unknowns or any(check.status == "unknown" for check in scene_checks):
        level = "部分适配"
    else:
        level = "高度适配"

    matched = [check.text for check in core_checks + hard_checks + scene_checks + preference_checks if check.status == "matched"]
    unmatched = [check.text for check in hard_checks if check.status == "mismatch"]
    unknown = [check.text for check in core_checks + hard_checks + scene_checks + preference_checks if check.status == "unknown"]

    reason_inputs: list[_RequirementCheck] = []
    for check in core_checks + hard_checks + scene_checks + preference_checks:
        if check.status == "matched":
            reason_inputs.append(check)
    reasons: list[dict[str, Any]] = []
    for check in reason_inputs:
        related_facts = [
            fact for fact in facts
            if fact.get("status") == "verified"
            and fact.get("traceable")
            and _overlap_status(check.text, f"{fact['field']} {fact['value']}")
        ]
        if not related_facts:
            continue
        fact = related_facts[0]
        reasons.append(
            {
                "customer_need": check.text,
                "product_fact": f"{fact['field']}：{fact['value']}",
                "conclusion": f"客户提出“{check.text}”；资料记录了上述产品事实，因此该项有证据支持。",
                "source_ids": fact["source_ids"],
            }
        )

    dimensions = {
        "core_needs": {"matched": [c.text for c in core_checks if c.status == "matched"], "unknown": [c.text for c in core_checks if c.status == "unknown"]},
        "budget": budget_check.status if budget_check else "not_provided",
        "usage_scenario": {"matched": [c.text for c in scene_checks if c.status == "matched"], "unknown": [c.text for c in scene_checks if c.status == "unknown"]},
        "hard_constraints": {"matched": [c.text for c in hard_checks if c.status == "matched"], "unmatched": [c.text for c in hard_checks if c.status == "mismatch"], "unknown": [c.text for c in hard_checks if c.status == "unknown"]},
        "preferences": {"matched": [c.text for c in preference_checks if c.status == "matched"], "unknown": [c.text for c in preference_checks if c.status == "unknown"]},
        "evidence_reliability": "可追溯来源" if has_traceable_source else "暂无可验证来源",
    }
    explanation = {
        "高度适配": "检索事实支持全部已解析核心需求，未发现硬性条件不满足；该结论不代表产品质量或统计概率。",
        "部分适配": "至少一项核心需求有来源事实支持，但仍有需求或场景待确认；不代表产品质量或统计概率。",
        "适配度较低": "至少一项明确硬性条件与已检索事实冲突，不作为正常首选推荐。",
        "信息不足，暂无法判断": "缺少可验证事实、关键硬性条件未核实，或尚未找到可支持核心需求的产品事实。",
    }[level]

    return {
        "product_id": candidate.product_id,
        "product_name": candidate.name,
        "product_model": candidate.model or next((fact["value"] for fact in facts if fact["field"] == "型号" and fact.get("status") != "conflict"), None),
        "recommendation_reasons": reasons,
        "key_facts": facts,
        "fit_assessment": {
            "level": level,
            "matched_requirements": matched,
            "unmatched_requirements": unmatched,
            "unknown_requirements": unknown,
            "dimensions": dimensions,
            "explanation": explanation,
        },
        "sources": [source.as_dict() for source in all_sources],
        "_hard_mismatches": len(hard_mismatches),
        "_hard_unknowns": len(hard_unknowns),
        "_core_matches": len(core_matches),
        "_traceable_fact_count": sum(
            1 for fact in facts
            if fact.get("status") == "verified" and fact.get("traceable")
        ),
    }


def _personalized_recommendation(profile: CustomerProfile, assessment: Mapping[str, Any]) -> dict[str, str]:
    fit = assessment.get("fit_assessment", {})
    dimensions = fit.get("dimensions", {})
    matched_requirements = set(fit.get("matched_requirements", []))
    reasons = assessment.get("recommendation_reasons", [])
    concerns = _split_items(profile.preferences)
    task = profile.customer_task
    context = []
    if profile.customer_type:
        context.append(f"您作为{profile.customer_type}")
    if profile.usage_scenario:
        context.append(f"主要在“{profile.usage_scenario}”使用")
    if task:
        context.append(f"首要任务是“{task}”")
    elif profile.need:
        context.append(f"本次需求是“{profile.need}”")

    explanation = "，".join(context) + "。" if context else "结合您提供的需求，"
    evidence_reasons = [
        f"“{reason.get('customer_need', '')}”对应的已核验资料为{reason.get('product_fact', '')}"
        for reason in reasons[:2]
    ]
    if evidence_reasons:
        explanation += "推荐依据：" + "；".join(evidence_reasons) + "。"
    else:
        explanation += "当前候选仍需结合可追溯产品资料核对，不能仅凭顾客身份或场景推断产品优势。"

    concern_notes = []
    for concern in concerns:
        matching_reason = next(
            (reason for reason in reasons if reason.get("customer_need") == concern),
            None,
        )
        if matching_reason:
            concern_notes.append(
                f"“{concern}”有对应资料事实：{matching_reason.get('product_fact', '')}"
            )
        else:
            concern_notes.append(f"“{concern}”尚缺少足够资料佐证，建议现场核验")
    if concern_notes:
        explanation += "优先顾虑：" + "；".join(concern_notes) + "。"

    validation_notes = [
        f"首要任务“{need}”尚未被产品资料直接证实，建议现场演练核验"
        for need in _split_needs(profile.customer_task)
        if need not in matched_requirements
    ]
    matched_scenarios = set(dimensions.get("usage_scenario", {}).get("matched", []))
    validation_notes.extend(
        f"使用场景“{scene}”尚未被产品资料直接证实，建议按该场景试用"
        for scene in _split_items(profile.usage_scenario)
        if scene not in matched_scenarios
    )
    if validation_notes:
        explanation += "需现场确认：" + "；".join(validation_notes) + "。"

    persona = profile.customer_type
    if any(label in persona for label in ("教师", "老师")):
        role_example = "您作为教师，可按备课和课堂准备的日常流程"
    elif "学生" in persona:
        role_example = "您作为学生，可按上课、自习或整理课程资料的日常流程"
    elif persona:
        role_example = f"您作为{persona}，可按自己的日常工作或学习流程"
    else:
        role_example = "您可按自己的日常使用流程"
    scene = f"“{profile.usage_scenario}”场景" if profile.usage_scenario else "实际使用场景"
    activity = f"完成“{task}”" if task else f"验证“{profile.need}”"
    example = f"例如，{role_example}，在{scene}中用实际资料{activity}。"
    if concerns:
        example += f"试用时按优先级逐项核对“{'、'.join(concerns)}”；资料未确认的项目，验证后再作购买判断。"
    else:
        example += "试用时按您的实际流程核对需求，并确认资料未覆盖的条件。"
    return {
        "customer_facing_reason": explanation,
        "example_scenario": example,
    }


def _public_assessment(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if not key.startswith("_")}


def _make_plan(
    *,
    status: str,
    requirements: RequirementSet,
    profile: CustomerProfile,
    recommendations: list[dict[str, Any]] | None = None,
    excluded: list[dict[str, Any]] | None = None,
    unresolved: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    sources: list[SourceReference] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "retrieval_status": status,
        "customer_requirements": requirements.as_dict(),
        "customer_facts": {
            "explicit": profile.explicit_fields(),
            "system_inferences": [],
            "interpretation_note": "未使用大模型；仅按输入原文和确定性规则整理，不补填未提供信息。",
        },
        "recommendations": recommendations or [],
        "excluded_products": excluded or [],
        "unresolved_candidates": unresolved or [],
        "sources": [source.as_dict() for source in (sources or [])],
        "warnings": warnings or [],
    }


def generate_recommendation_plan(
    customer: CustomerProfile | Mapping[str, Any],
    retriever: Callable[..., RetrievalResponse] = retrieve_with_adapter,
) -> dict[str, Any]:
    """Build a validated, deterministic recommendation plan from returned facts."""

    try:
        profile = customer if isinstance(customer, CustomerProfile) else CustomerProfile.from_values(customer)
    except (TypeError, ValueError) as exc:
        empty = CustomerProfile(need="")
        requirements = RequirementSet([], [], [], [], None, [], ["客户需求描述必填"])
        return _make_plan(
            status="invalid_input",
            requirements=requirements,
            profile=empty,
            warnings=[str(exc)],
        )

    requirements, warnings, invalid_reason = _profile_and_requirements(profile)
    if invalid_reason:
        return _make_plan(
            status="invalid_input",
            requirements=requirements,
            profile=profile,
            warnings=warnings,
        )

    try:
        response = retriever(profile.retrieval_query(), top_k=RETRIEVAL_TOP_K)
        if not isinstance(response, RetrievalResponse):
            raise RetrievalAdapterError("retriever returned an invalid response")
    except Exception:
        LOGGER.exception("Recommendation retrieval failed")
        return _make_plan(
            status="error",
            requirements=requirements,
            profile=profile,
            warnings=warnings + ["检索接口调用失败，未生成推荐。请检查本地检索器配置和终端日志。"],
        )

    if response.mode == "mock":
        warnings.append("当前为 Mock 演示模式：候选与事实来自本地精选资料，不代表已接入真实检索索引。")
    warnings.extend(response.warnings)
    if not response.results:
        warnings.append("当前知识库未检索到候选片段；请补充型号、场景或具体参数后重试。")
        return _make_plan(
            status="no_results",
            requirements=requirements,
            profile=profile,
            warnings=warnings,
        )

    candidates, all_sources = _build_candidates(response)
    if not candidates:
        warnings.append("检索片段中没有能够核验的产品名称，不能凭空生成候选产品。")
        return _make_plan(
            status="insufficient_evidence",
            requirements=requirements,
            profile=profile,
            warnings=warnings,
            sources=all_sources,
        )

    sources_by_id = {source.id: source for source in all_sources}
    assessments = [
        _assess_candidate(candidate, requirements, sources_by_id)
        for candidate in candidates.values()
    ]
    for assessment in assessments:
        assessment.update(_personalized_recommendation(profile, assessment))
    assessments.sort(
        key=lambda item: (
            item["_hard_mismatches"],
            item["_hard_unknowns"],
            -item["_core_matches"],
            -item["_traceable_fact_count"],
            item["product_name"].casefold(),
        )
    )

    excluded = [item for item in assessments if item["_hard_mismatches"] > 0]
    unresolved = [
        item for item in assessments
        if item["_hard_mismatches"] == 0
        and (item["_hard_unknowns"] > 0 or item["_core_matches"] == 0)
    ]
    eligible = [
        item for item in assessments
        if item["_hard_mismatches"] == 0
        and item["_hard_unknowns"] == 0
        and item["_core_matches"] > 0
    ]
    recommendations = [_public_assessment(item) for item in eligible[:MAX_RECOMMENDATIONS]]
    excluded_public = [_public_assessment(item) for item in excluded]
    unresolved_public = [_public_assessment(item) for item in unresolved]

    if excluded and not recommendations and not unresolved:
        status = "no_suitable_products"
        warnings.append("所有可识别候选均明确不满足至少一项硬性条件，未列入正常推荐。")
    elif not recommendations:
        status = "insufficient_evidence"
        warnings.append("暂无足够证据形成可靠推荐方案；待核验候选仅供补充检索，不作为推荐。")
    else:
        status = "success"
    if excluded:
        warnings.append(f"有 {len(excluded)} 个候选明确违反硬性条件，已单独列出并从正常推荐中排除。")
    if unresolved:
        warnings.append(f"有 {len(unresolved)} 个候选仍有关键条件或核心需求未验证，未列入正常推荐。")

    return _make_plan(
        status=status,
        requirements=requirements,
        profile=profile,
        recommendations=recommendations,
        excluded=excluded_public,
        unresolved=unresolved_public,
        warnings=warnings,
        sources=all_sources,
    )


def _markdown_escape(value: Any) -> str:
    text = str(value)
    return re.sub(r"([\\`*_\[\]<>|])", r"\\\1", text)


def _format_source(source: Mapping[str, Any]) -> str:
    title = _markdown_escape(source.get("title") or "来源未提供")
    if source.get("demo"):
        title = "[Mock 演示资料] " + title
    url = _safe_url(source.get("url"))
    rendered = f"[{title}](<{url}>)" if url else f"**{title}**"
    location = []
    if source.get("local_path"):
        location.append(f"文件：`{_markdown_escape(source['local_path'])}`")
    if source.get("page") is not None:
        location.append(f"页码：{_markdown_escape(source['page'])}")
    if source.get("section"):
        location.append(f"章节：{_markdown_escape(source['section'])}")
    if source.get("line_start") is not None:
        line = str(source["line_start"])
        if source.get("line_end") not in (None, source.get("line_start")):
            line += f"-{source['line_end']}"
        location.append(f"行号：{_markdown_escape(line)}")
    if source.get("original_source_id"):
        location.append(f"来源 ID：`{_markdown_escape(source['original_source_id'])}`")
    return rendered + ("（" + "；".join(location) + "）" if location else "")


def render_customer_requirements(plan: Mapping[str, Any]) -> str:
    requirements = plan.get("customer_requirements", {})
    facts = plan.get("customer_facts", {})
    lines = ["### 需求解析", "**客户明确输入**（非空字段）："]
    explicit = facts.get("explicit", {})
    for label, value in explicit.items():
        if value:
            lines.append(f"- **{_markdown_escape(label)}：** {_markdown_escape(value)}")
    if not any(explicit.values()):
        lines.append("- 暂无")
    lines.append("\n**规则整理**：")
    for key, label in (("core_needs", "核心需求"), ("hard_constraints", "硬性条件"), ("preferences", "偏好"), ("rejected_features", "不接受特征"), ("usage_scenarios", "使用场景"), ("unknowns", "待确认")):
        values = requirements.get(key) or []
        if values:
            lines.append(f"- **{label}：** " + "；".join(_markdown_escape(value) for value in values))
    budget = requirements.get("budget")
    if budget:
        lines.append(f"- **预算解析：** {_markdown_escape(budget.get('raw'))}（币种：{_markdown_escape(budget.get('currency') or '未明确')}）")
    lines.append("\n系统推断：无；未提供的信息不会自动补齐。")
    return "\n".join(lines)


def _render_product(item: Mapping[str, Any], heading: str) -> list[str]:
    fit = item.get("fit_assessment", {})
    lines = [f"### {heading}：{_markdown_escape(item.get('product_name') or '产品名称未提供')}"]
    identity = []
    if item.get("product_id"):
        identity.append(f"ID：`{_markdown_escape(item['product_id'])}`")
    if item.get("product_model"):
        identity.append(f"型号：`{_markdown_escape(item['product_model'])}`")
    if identity:
        lines.append("；".join(identity))
    lines.append(f"**适配程度：{_markdown_escape(fit.get('level') or '信息不足，暂无法判断')}**")
    lines.append(_markdown_escape(fit.get("explanation") or "暂无适配解释。"))
    if item.get("customer_facing_reason"):
        lines.append(f"\n**结合顾客需求：** {_markdown_escape(item['customer_facing_reason'])}")
    if item.get("example_scenario"):
        lines.append(f"\n**建议现场体验：** {_markdown_escape(item['example_scenario'])}")

    reasons = item.get("recommendation_reasons") or []
    lines.append("\n**推荐理由（需求 → 事实 → 结论）**")
    if reasons:
        for reason in reasons:
            lines.append(
                f"- 客户需求：{_markdown_escape(reason.get('customer_need', ''))}；"
                f"产品事实：{_markdown_escape(reason.get('product_fact', ''))}；"
                f"结论：{_markdown_escape(reason.get('conclusion', ''))}"
            )
    else:
        lines.append("- 暂无能同时关联客户需求和产品事实的理由。")

    lines.append("\n**关键产品事实**")
    facts = item.get("key_facts") or []
    if facts:
        for fact in facts:
            value = fact.get("value", "资料未提供")
            if fact.get("status") == "conflict":
                values = fact.get("conflicting_values", [])
                detail = "；".join(
                    f"{_markdown_escape(value_item.get('value'))}（来源：{', '.join(value_item.get('source_ids', []))}）"
                    for value_item in values
                )
                lines.append(f"- **{_markdown_escape(fact.get('field'))}：来源冲突** {detail}")
            else:
                lines.append(f"- **{_markdown_escape(fact.get('field'))}：** {_markdown_escape(value)}")
            if fact.get("source_ids"):
                lines.append(f"  - 事实来源 ID：{', '.join(fact['source_ids'])}")
            if not fact.get("traceable"):
                lines.append("  - ⚠️ 来源不可追溯，不能视为已验证事实。")
    else:
        lines.append("- 资料未提供可核验的产品参数。")

    for key, label in (("matched_requirements", "匹配项"), ("unmatched_requirements", "不匹配项"), ("unknown_requirements", "待确认项")):
        values = fit.get(key) or []
        lines.append(f"\n**{label}**：" + ("；".join(_markdown_escape(value) for value in values) if values else "无"))

    lines.append("\n**来源**")
    product_sources = item.get("sources") or []
    if product_sources:
        for source in product_sources:
            lines.append(f"- {_format_source(source)}")
    else:
        lines.append("- 暂无可验证来源。")
    return lines


def render_recommendation_results(plan: Mapping[str, Any]) -> str:
    status = plan.get("retrieval_status")
    lines: list[str] = []
    recommendations = plan.get("recommendations") or []
    if recommendations:
        lines.append("## 推荐方案")
        lines.append("适配结论按明确条件和可追溯事实判定，不是质量排名或统计概率。")
        for index, item in enumerate(recommendations, start=1):
            lines.extend(_render_product(item, f"推荐 {index}"))
    elif status == "error":
        lines.append("## 暂时无法完成推荐")
    elif status == "no_results":
        lines.append("## 未命中候选产品")
        lines.append("当前知识库没有返回候选片段；请补充具体型号、场景或必要参数后重试。")
    elif status == "no_suitable_products":
        lines.append("## 暂无合适产品")
        lines.append("所有可识别候选都明确违反至少一项硬性条件，未将其列为正常推荐。")
    else:
        lines.append("## 暂无足够证据形成可靠推荐方案")
        lines.append("候选缺少可验证事实、关键条件仍未知，或检索片段中没有可核验产品名称。")

    for title, key in (("待核验候选", "unresolved_candidates"), ("硬性条件不满足，已排除", "excluded_products")):
        items = plan.get(key) or []
        if items:
            lines.append(f"\n## {title}")
            for item in items:
                lines.extend(_render_product(item, "候选"))

    warnings = plan.get("warnings") or []
    if warnings:
        lines.append("\n## 提示")
        lines.extend(f"- {_markdown_escape(warning)}" for warning in warnings)
    return "\n".join(lines)


def run_recommendation(
    need: str,
    customer_type: str = "",
    usage_scenario: str = "",
    budget_text: str = "",
    hard_conditions: str = "",
    preferences: str = "",
    rejected_features: str = "",
    notes: str = "",
    retriever: Callable[..., RetrievalResponse] = retrieve_with_adapter,
    customer_task: str = "",
) -> tuple[str, str, str]:
    """Gradio callback kept thin so the recommendation engine stays testable."""

    profile = {
        "need": need,
        "customer_task": customer_task,
        "customer_type": customer_type,
        "usage_scenario": usage_scenario,
        "budget_text": budget_text,
        "hard_conditions": hard_conditions,
        "preferences": preferences,
        "rejected_features": rejected_features,
        "notes": notes,
    }
    plan = generate_recommendation_plan(profile, retriever=retriever)
    status_labels = {
        "success": "已生成推荐方案",
        "invalid_input": "客户信息存在空项或矛盾，请按提示修正。",
        "no_results": "检索未命中候选产品。",
        "no_suitable_products": "候选产品均不满足硬性条件。",
        "insufficient_evidence": "暂无足够证据形成可靠推荐方案。",
        "error": "检索接口运行失败，未生成推荐。",
    }
    status = status_labels.get(plan["retrieval_status"], "未能完成推荐。")
    return (
        render_customer_requirements(plan),
        render_recommendation_results(plan),
        status,
    )
