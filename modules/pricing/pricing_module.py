"""门店增长智能体：可核验价格与报价状态模块。

本模块只处理价格事实，不计算未授权的门店折扣、补贴或成交价。
队友接入方式：
    from modules.pricing.pricing_module import get_quote_status
    result = get_quote_status("HUAWEI MateBook 14（鸿蒙版）", "预算6000元")

返回值是可直接序列化为 JSON 的 dict，不依赖第三方包。
"""

from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from statistics import median
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


DEFAULT_CSV = (
    Path(__file__).resolve().parents[2]
    / "knowledge-base"
    / "华为PC全板块深度知识库_v7"
    / "P1-产品参数库"
    / "08-官方公开价格快照"
    / "官方价格快照.csv"
)
DEFAULT_COMPETITOR_COMPARISON_CSV = DEFAULT_CSV.with_name("竞品可比配置价格与性能快照.csv")

# 只有明确出现这些状态时，才阻止展示金额；不凭空推断库存或成交状态。
BLOCKED_STATUS_WORDS = ("下架", "未公开", "无当前公开", "官方询价")
COMPARABLE_PRICE_BASES = ("官方商城页面价", "当前商城页面价")
OFFICIAL_COMPETITOR_DOMAINS = {
    "apple": ("apple.com", "apple.com.cn"),
    "samsung": ("samsung.com", "samsung.com.cn"),
    "vivo": ("vivo.com", "vivo.com.cn"),
}
COMPETITOR_BRAND_ALIASES = {
    "苹果": "apple",
    "apple": "apple",
    "三星": "samsung",
    "samsung": "samsung",
    "vivo": "vivo",
}
MAX_COMPARISON_SNAPSHOT_GAP_DAYS = 31
MAX_BENCHMARK_SCORE_GAP = 0.10


@dataclass(frozen=True)
class PriceRecord:
    record_id: str
    product_name: str
    original_name: str
    category: str
    configuration: str
    sku: str
    price_type: str
    page_price: Optional[float]
    reference_price: Optional[float]
    condition: str
    stock_status: str
    region: str
    verified_at: str
    source_title: str
    source_url: str
    evidence: str
    verification_status: str
    mapping_note: str
    processor: str = ""
    memory_gb: Optional[float] = None
    storage_gb: Optional[float] = None
    display_size_in: Optional[float] = None
    benchmark_name: str = ""
    benchmark_version: str = ""
    benchmark_score: Optional[float] = None
    benchmark_unit: str = ""
    benchmark_verified: bool = False
    benchmark_source_title: str = ""
    benchmark_source_url: str = ""


@dataclass(frozen=True)
class QuoteResult:
    product: str
    configuration: str
    public_price: Optional[float]
    reference_price: Optional[float]
    currency: str
    price_basis: str
    baseline_date: str
    source_title: str
    source_url: str
    stock_status: str
    status: str
    status_label: str
    manual_review_items: List[str]
    evidence: str
    record_id: str
    competitor_comparisons: List[Dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def _number(value: str) -> Optional[float]:
    """Parse CSV money fields without treating missing values as zero."""
    if not value or not value.strip():
        return None
    cleaned = re.sub(r"[^0-9.]", "", value)
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _record(row: Dict[str, str]) -> PriceRecord:
    return PriceRecord(
        record_id=row.get("记录ID", "").strip(),
        product_name=row.get("规范产品名称", "").strip(),
        original_name=row.get("原始产品名称", "").strip(),
        category=row.get("分类", "").strip(),
        configuration=row.get("精确款式", "").strip(),
        sku=row.get("型号或SKU", "").strip(),
        price_type=row.get("价格类型", "").strip(),
        page_price=_number(row.get("页面金额（元）", "")),
        reference_price=_number(row.get("参考或划线金额（元）", "")),
        condition=row.get("条件摘要", "").strip(),
        stock_status=row.get("库存状态", "").strip(),
        region=row.get("地区上下文", "").strip(),
        verified_at=row.get("核验时间", "").strip(),
        source_title=row.get("来源标题", "").strip(),
        source_url=row.get("官方URL", "").strip(),
        evidence=row.get("证据摘要", "").strip(),
        verification_status=row.get("核验状态", "").strip(),
        mapping_note=row.get("映射备注", "").strip(),
        processor=row.get("处理器", "").strip(),
        memory_gb=_number(row.get("内存（GB）", "")),
        storage_gb=_number(row.get("存储（GB）", "")),
        display_size_in=_number(row.get("屏幕尺寸（英寸）", "")),
        benchmark_name=row.get("跑分项目", "").strip(),
        benchmark_version=row.get("跑分版本", "").strip(),
        benchmark_score=_number(row.get("跑分", "")),
        benchmark_unit=row.get("跑分单位", "").strip(),
        benchmark_verified="已核验" in row.get("跑分核验状态", ""),
        benchmark_source_title=row.get("跑分来源标题", "").strip(),
        benchmark_source_url=row.get("跑分来源URL", "").strip(),
    )


@dataclass(frozen=True)
class CompetitorPriceRecord:
    """A competitor snapshot is usable only with complete price and benchmark evidence."""

    brand: str
    product_name: str
    configuration: str
    sku: str
    category: str
    price: Optional[float]
    price_type: str
    verified_at: str
    source_title: str
    source_url: str
    verification_status: str
    evidence: str
    processor: str
    memory_gb: Optional[float]
    storage_gb: Optional[float]
    display_size_in: Optional[float]
    benchmark_name: str
    benchmark_version: str
    benchmark_score: Optional[float]
    benchmark_unit: str
    benchmark_verified: bool
    benchmark_source_title: str
    benchmark_source_url: str


def _snapshot_value(record: object, *names: str, default: Any = "") -> Any:
    for name in names:
        if isinstance(record, Mapping) and name in record:
            value = record[name]
        else:
            value = getattr(record, name, None)
        if value is not None and value != "":
            return value
    return default


def _float_value(value: Any) -> Optional[float]:
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    numbers = re.findall(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    if len(numbers) != 1:
        return None
    try:
        return float(numbers[0])
    except ValueError:
        return None


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y", "已核验", "verified"}


def _capacity(text: Any, kind: str) -> Optional[float]:
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    raw = str(text or "").strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return float(raw)
    labels = (kind, "内存" if kind == "memory" else "存储")
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?:{label_pattern})\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(GB|TB)", raw, re.I)
    if not match:
        # Configurations such as 16GB/512GB are parsed by the caller only when
        # the requested capacity is explicitly labelled; never concatenate numbers.
        return None
    amount = float(match.group(1))
    return amount * 1024 if match.group(2).upper() == "TB" else amount


def _coerce_competitor_record(value: object) -> CompetitorPriceRecord:
    status = str(_snapshot_value(value, "verification_status", "status", "核验状态", default="")).strip()
    benchmark_status = str(_snapshot_value(value, "benchmark_status", default="")).strip()
    benchmark_verified = _snapshot_value(value, "benchmark_verified", default=None)
    if benchmark_verified is None:
        benchmark_verified = "已核验" in benchmark_status or "verified" in benchmark_status.casefold()
    config = str(_snapshot_value(value, "configuration", "config", "精确款式", default="")).strip()
    return CompetitorPriceRecord(
        brand=str(_snapshot_value(value, "brand", "品牌", default="")).strip(),
        product_name=str(_snapshot_value(value, "product_name", "product", "model", "产品名称", default="")).strip(),
        configuration=config,
        sku=str(_snapshot_value(value, "sku", "型号或SKU", default="")).strip(),
        category=str(_snapshot_value(value, "category", "分类", default="")).strip(),
        price=_float_value(_snapshot_value(value, "price", "page_price", "public_price", "页面金额（元）", default=None)),
        price_type=str(_snapshot_value(value, "price_type", "price_basis", "价格类型", default="")).strip(),
        verified_at=str(_snapshot_value(value, "verified_at", "date", "核验时间", default="")).strip(),
        source_title=str(_snapshot_value(value, "source_title", "price_source_title", "来源标题", default="")).strip(),
        source_url=str(_snapshot_value(value, "source_url", "price_source_url", "url", "官方URL", default="")).strip(),
        verification_status=status,
        evidence=str(_snapshot_value(value, "evidence", "price_evidence", "证据摘要", default="")).strip(),
        processor=str(_snapshot_value(value, "processor", "cpu", "处理器", default="")).strip(),
        memory_gb=_capacity(_snapshot_value(value, "memory_gb", "memory", "内存", default=None), "memory"),
        storage_gb=_capacity(_snapshot_value(value, "storage_gb", "storage", "存储", default=None), "storage"),
        display_size_in=_float_value(_snapshot_value(value, "display_size_in", "screen_size", "屏幕尺寸", default=None)),
        benchmark_name=str(_snapshot_value(value, "benchmark_name", "benchmark", "跑分项目", default="")).strip(),
        benchmark_version=str(_snapshot_value(value, "benchmark_version", "跑分版本", default="")).strip(),
        benchmark_score=_float_value(_snapshot_value(value, "benchmark_score", "score", "跑分", default=None)),
        benchmark_unit=str(_snapshot_value(value, "benchmark_unit", "跑分单位", default="")).strip(),
        benchmark_verified=_bool_value(benchmark_verified),
        benchmark_source_title=str(_snapshot_value(value, "benchmark_source_title", "跑分来源标题", default="")).strip(),
        benchmark_source_url=str(_snapshot_value(value, "benchmark_source_url", "跑分来源URL", default="")).strip(),
    )


def load_competitor_price_records(csv_path: Optional[Path | str] = None) -> List[CompetitorPriceRecord]:
    """Load optional competitor evidence; a missing file intentionally means no comparisons."""
    path = Path(csv_path) if csv_path else DEFAULT_COMPETITOR_COMPARISON_CSV
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [_coerce_competitor_record(row) for row in csv.DictReader(handle)]


def _date_value(value: Any) -> Optional[datetime]:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _verified_status(value: Any) -> bool:
    text = str(value or "").casefold()
    return "已核验" in text or "verified" in text


def _official_source(brand: str, url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    key = COMPETITOR_BRAND_ALIASES.get(brand.strip().casefold(), "")
    return bool(key and any(host == domain or host.endswith("." + domain) for domain in OFFICIAL_COMPETITOR_DOMAINS[key]))


def _price_source_allowed(record: CompetitorPriceRecord) -> bool:
    if not record.product_name or not record.configuration or not record.sku:
        return False
    if not record.source_url.startswith("https://") or not _verified_status(record.verification_status):
        return False
    if record.price_type not in COMPARABLE_PRICE_BASES:
        return False
    return _official_source(record.brand, record.source_url)


def _huawei_source_allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in ("huawei.com", "vmall.com"))


def _family(text: str) -> str:
    value = text.casefold()
    if any(word in value for word in ("电脑", "笔记本", "macbook", "matebook", "laptop", "galaxy book", "book", "pc")):
        return "computer"
    if any(word in value for word in ("平板", "tablet", "ipad")):
        return "tablet"
    if any(word in value for word in ("手机", "phone", "iphone", "galaxy", "x200")):
        return "phone"
    return ""


def _hardware(record: object) -> Dict[str, Any]:
    config = str(_snapshot_value(record, "configuration", "config", "精确款式", default=""))
    return {
        "processor": str(_snapshot_value(record, "processor", "cpu", "处理器", default="")).strip(),
        "memory_gb": _float_value(_snapshot_value(record, "memory_gb", "memory", "内存", default=None)),
        "storage_gb": _float_value(_snapshot_value(record, "storage_gb", "storage", "存储", default=None)),
        "display_size_in": _float_value(_snapshot_value(record, "display_size_in", "screen_size", "屏幕尺寸", default=None)),
        "configuration": config,
        "sku": str(_snapshot_value(record, "sku", "型号或SKU", default="")).strip(),
    }


def _benchmark(record: object) -> Dict[str, Any]:
    return {
        "name": str(_snapshot_value(record, "benchmark_name", "benchmark", "跑分项目", default="")).strip(),
        "version": str(_snapshot_value(record, "benchmark_version", "跑分版本", default="")).strip(),
        "score": _float_value(_snapshot_value(record, "benchmark_score", "score", "跑分", default=None)),
        "unit": str(_snapshot_value(record, "benchmark_unit", "跑分单位", default="")).strip(),
        "verified": _bool_value(_snapshot_value(record, "benchmark_verified", default=False)),
        "source_title": str(_snapshot_value(record, "benchmark_source_title", "跑分来源标题", default="")).strip(),
        "source_url": str(_snapshot_value(record, "benchmark_source_url", "跑分来源URL", default="")).strip(),
    }


def _evidence_link(record: object) -> Dict[str, str]:
    return {
        "title": str(_snapshot_value(record, "source_title", "price_source_title", "来源标题", default="")).strip(),
        "url": str(_snapshot_value(record, "source_url", "price_source_url", "url", "官方URL", default="")).strip(),
        "date": str(_snapshot_value(record, "verified_at", "date", "核验时间", default="")).strip()[:10],
    }


def compare_price_snapshots(
    huawei_record: object,
    competitor_records: Iterable[object],
) -> List[Dict[str, object]]:
    """Return only evidence-complete competitor savings comparisons.

    Both sides need a verified page price, matching memory/storage, a same-version
    benchmark with scores within 10%, traceable sources, and snapshots within 31
    days. Missing evidence rejects the candidate rather than producing a guess.
    """
    h_price = _float_value(_snapshot_value(huawei_record, "page_price", "public_price", "price", default=None))
    h_status = _snapshot_value(huawei_record, "verification_status", "status", default="")
    h_basis = str(_snapshot_value(huawei_record, "price_type", "price_basis", default=""))
    h_source = str(_snapshot_value(huawei_record, "source_url", "url", default=""))
    h_date = _date_value(_snapshot_value(huawei_record, "verified_at", "baseline_date", "date", default=""))
    h_hw = _hardware(huawei_record)
    h_bench = _benchmark(huawei_record)
    h_family = _family(str(_snapshot_value(huawei_record, "category", "product", "product_name", default="")))
    if not (h_price and h_price > 0 and _verified_status(h_status) and h_basis in COMPARABLE_PRICE_BASES and h_date and _huawei_source_allowed(h_source)):
        return []
    if not h_family or not h_bench["verified"] or not h_bench["source_url"].startswith("https://"):
        return []
    if not h_hw["configuration"] or not h_hw["sku"] or not h_hw["processor"]:
        return []
    if h_hw["memory_gb"] is None or h_hw["storage_gb"] is None:
        return []
    results: List[Dict[str, object]] = []
    for raw in competitor_records:
        competitor = _coerce_competitor_record(raw)
        c_date = _date_value(competitor.verified_at)
        c_hw = _hardware(competitor)
        c_bench = _benchmark(competitor)
        c_family = _family(" ".join((competitor.category, competitor.product_name)))
        if not (competitor.price and competitor.price > h_price and _price_source_allowed(competitor)):
            continue
        if not c_date or abs((c_date - h_date).days) > MAX_COMPARISON_SNAPSHOT_GAP_DAYS:
            continue
        if not h_family or c_family != h_family:
            continue
        if not c_hw["configuration"] or not c_hw["sku"] or not c_hw["processor"]:
            continue
        if c_hw["memory_gb"] is None or c_hw["storage_gb"] is None:
            continue
        if c_hw["memory_gb"] != h_hw["memory_gb"] or c_hw["storage_gb"] != h_hw["storage_gb"]:
            continue
        if h_hw["display_size_in"] is not None and c_hw["display_size_in"] is not None and abs(h_hw["display_size_in"] - c_hw["display_size_in"]) > 1.5:
            continue
        if not (c_bench["verified"] and c_bench["source_url"].startswith("https://")):
            continue
        if not h_bench["name"] or h_bench["name"].casefold() != c_bench["name"].casefold():
            continue
        if not h_bench["version"] or h_bench["version"] != c_bench["version"] or h_bench["unit"] != c_bench["unit"]:
            continue
        if not h_bench["score"] or not c_bench["score"]:
            continue
        score_gap = abs(h_bench["score"] - c_bench["score"]) / max(h_bench["score"], c_bench["score"])
        if score_gap > MAX_BENCHMARK_SCORE_GAP:
            continue
        savings = round(competitor.price - h_price, 2)
        competitor_name = competitor.product_name or competitor.sku
        brand = competitor.brand or "友商"
        results.append({
            "headline": f"比{brand}的{competitor_name}同配置产品便宜¥{savings:,.0f}",
            "competitor_brand": brand,
            "competitor_product": competitor_name,
            "savings": savings,
            "huawei_price": h_price,
            "competitor_price": competitor.price,
            "price_difference": savings,
            "configuration_comparison": {
                "huawei": h_hw,
                "competitor": c_hw,
                "matched_fields": ["内存", "存储"] + (["屏幕尺寸"] if h_hw["display_size_in"] is not None and c_hw["display_size_in"] is not None else []),
            },
            "benchmark_comparison": {
                "name": h_bench["name"], "version": h_bench["version"], "unit": h_bench["unit"],
                "huawei_score": h_bench["score"], "competitor_score": c_bench["score"],
                "relative_gap": round(score_gap, 4),
            },
            "sources": {"huawei_price": _evidence_link(huawei_record), "competitor_price": _evidence_link(competitor),
                        "huawei_benchmark": {"title": h_bench["source_title"], "url": h_bench["source_url"]},
                        "competitor_benchmark": {"title": c_bench["source_title"], "url": c_bench["source_url"]}},
            "disclaimer": "价格为同一时间窗口的公开页面快照，不代表当前库存、成交价、补贴或购买承诺；跑分仅用于本次同口径筛选。",
        })
    return sorted(results, key=lambda item: float(item["savings"]), reverse=True)


def build_competitor_price_comparison(
    product_query: str,
    records: Optional[Iterable[PriceRecord]] = None,
    competitor_records: Optional[Iterable[object]] = None,
) -> List[Dict[str, object]]:
    """Find the Huawei snapshot and return qualifying competitor savings only."""
    matches = find_price_records(product_query, records=records)
    huawei = next((item for item in matches if item.page_price is not None and _verified_status(item.verification_status) and not _blocked(item)), None)
    if huawei is None:
        return []
    candidates = list(competitor_records) if competitor_records is not None else load_competitor_price_records()
    return compare_price_snapshots(huawei, candidates)


# Explicit aliases make the evidence gate easy to use from integrations and tests.
find_competitor_price_advantages = compare_price_snapshots


def load_price_records(csv_path: Optional[Path | str] = None) -> List[PriceRecord]:
    """Load the official snapshot CSV. Missing data raises a clear local error."""
    path = Path(csv_path) if csv_path else DEFAULT_CSV
    if not path.exists():
        raise FileNotFoundError(
            f"找不到价格快照：{path}\n"
            "请确认仓库根目录的 knowledge-base 目录已准备好。"
        )
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [_record(row) for row in csv.DictReader(handle)]


_PRICE_GENERIC_TERMS = {"huawei", "华为", "matebook", "电脑", "笔记本", "产品", "配置", "价格"}


def _match_terms(text: str) -> set[str]:
    """Return whole search terms; never use arbitrary substring matching for prices."""
    return set(re.findall(r"[a-z0-9]+|[\u3400-\u4dbf\u4e00-\u9fff]+", (text or "").casefold()))


def _match_score(record: PriceRecord, query: str) -> int:
    """Score only complete, product-identifying queries against one price record."""
    query_terms = _match_terms(query)
    meaningful_terms = query_terms - _PRICE_GENERIC_TERMS
    if not meaningful_terms:
        return 0
    record_terms = _match_terms(" ".join(
        [record.product_name, record.original_name, record.configuration, record.sku]
    ))
    if not query_terms.issubset(record_terms):
        return 0
    # A price must be tied to a model/SKU discriminator, not merely to its brand.
    has_discriminator = any(
        any(char.isdigit() for char in term) or term not in {"pro", "鸿蒙版", "酷睿", "麒麟"}
        for term in meaningful_terms
    )
    return len(query_terms) if has_discriminator else 0


def find_price_records(
    product_query: str,
    records: Optional[Iterable[PriceRecord]] = None,
    limit: int = 5,
) -> List[PriceRecord]:
    """Find exact-ish product records, keeping the most evidence-rich records first."""
    query = (product_query or "").strip()
    if not query:
        return []
    pool = list(records) if records is not None else load_price_records()
    ranked = [(record, _match_score(record, query)) for record in pool]
    ranked = [(record, score) for record, score in ranked if score > 0]
    ranked.sort(
        key=lambda item: (
            item[1],
            item[0].page_price is not None,
            "已核验" in item[0].verification_status,
            item[0].verified_at,
        ),
        reverse=True,
    )
    return [record for record, _ in ranked[:limit]]


def _date_only(timestamp: str) -> str:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", timestamp or "")
    return match.group(1) if match else (timestamp or "待核验")


def _manual_items(record: Optional[PriceRecord]) -> List[str]:
    common = [
        "门店四级价格规则及授权折扣未提供，不能推算最终成交价",
        "请人工确认客户地区、渠道、客户类型和购买数量",
        "请人工确认当前库存、配送条件和报价有效期",
        "如涉及补贴、以旧换新、分期或赠品，请核对当日授权记录",
    ]
    if record is None:
        return ["未找到匹配的官方价格记录"] + common
    if not record.configuration:
        common.insert(0, "当前记录缺少完整配置，需确认型号、内存、存储、颜色和系统")
    if record.reference_price is not None and record.page_price is not None:
        common.append("参考/划线金额不能直接视为可叠加优惠或成交价")
    if record.stock_status:
        common.append("库存和交付信息为快照，发送报价前需重新核验")
    return common


def _blocked(record: PriceRecord) -> bool:
    text = " ".join(
        [record.price_type, record.stock_status, record.evidence, record.verification_status]
    )
    return any(word in text for word in BLOCKED_STATUS_WORDS)


def build_quote_status(
    product_query: str,
    records: Optional[Iterable[PriceRecord]] = None,
    competitor_records: Optional[Iterable[object]] = None,
) -> QuoteResult:
    """Build one safe quote result for the team app.

    A public snapshot amount is shown only when it is present, verified, and not
    explicitly blocked by the source status. The result still carries manual
    review items because the P4 four-level store pricing data is unavailable.
    """
    matches = find_price_records(product_query, records=records)
    verified_matches = [
        item for item in matches
        if item.page_price is not None
        and "已核验" in item.verification_status
        and not _blocked(item)
    ]
    # A series name can legitimately match multiple SKU snapshots. Selecting the
    # first one would turn an incomplete request into somebody else's price.
    record = verified_matches[0] if len(verified_matches) == 1 else None

    if record is None:
        fallback = matches[0] if len(matches) == 1 else None
        ambiguous = len(verified_matches) > 1 or len(matches) > 1
        review_items = _manual_items(fallback)
        if ambiguous:
            review_items.insert(0, "输入对应多个型号或 SKU，不能擅自选择其中一条价格记录")
        elif fallback is not None:
            review_items.insert(0, "该记录不满足当前公开价格展示条件，不能输出具体金额")
        return QuoteResult(
            # Keep the requested identity visible; never substitute a nearby record.
            product=product_query.strip(),
            configuration="待确认具体配置",
            public_price=None,
            reference_price=None,
            currency="CNY",
            price_basis="暂无可核验公开价格",
            baseline_date="待核验",
            source_title="暂无可唯一对应的来源",
            source_url="",
            stock_status="待核验",
            status="manual_review",
            status_label="待人工核验，暂不输出具体成交价",
            manual_review_items=review_items,
            evidence="未找到唯一且可展示的官方价格快照",
            record_id="",
            competitor_comparisons=[],
        )

    comparisons = compare_price_snapshots(
        record,
        list(competitor_records) if competitor_records is not None else load_competitor_price_records(),
    )
    return QuoteResult(
        product=record.product_name,
        configuration=record.configuration or "具体配置待确认",
        public_price=record.page_price,
        reference_price=record.reference_price,
        currency="CNY",
        price_basis=record.price_type,
        baseline_date=_date_only(record.verified_at),
        source_title=record.source_title,
        source_url=record.source_url,
        stock_status=record.stock_status or "未提供",
        status="public_snapshot",
        status_label="可展示官方公开价格快照；最终成交价仍需人工确认",
        manual_review_items=_manual_items(record),
        evidence=record.evidence,
        record_id=record.record_id,
        competitor_comparisons=comparisons,
    )


def analyze_price_trend(
    price_points: Iterable[Dict[str, object]],
    horizon_days: int = 30,
) -> Dict[str, object]:
    """Robust 30-day trend baseline over verified, comparable public observations.

    Required fields: date, price, sku, price_basis, source URL, verified=True.
    Only Huawei/Vmall official domains are accepted. This remains a forecast,
    not a quote or guarantee; it must never replace an authorized price list.
    """
    if not 1 <= int(horizon_days) <= 90:
        raise ValueError("horizon_days must be between 1 and 90")
    clean = {}
    conflicts = set()
    rejected = 0
    sku_values, basis_values = set(), set()
    official_domains = ("huawei.com", "vmall.com")
    for point in price_points:
        try:
            day = datetime.strptime(str(point["date"])[:10], "%Y-%m-%d").date()
            price = float(point["price"])
            sku = str(point["sku"]).strip()
            basis = str(point["price_basis"]).strip()
            source = str(point["source"]).strip()
            host = (urlparse(source).hostname or "").lower()
            official = any(host == domain or host.endswith("." + domain) for domain in official_domains)
            if price <= 0 or not sku or not basis or not official or point.get("verified") is not True:
                rejected += 1
                continue
            sku_values.add(sku)
            basis_values.add(basis)
            if day in clean and clean[day] != price:
                conflicts.add(day)
            else:
                clean[day] = price
        except (KeyError, TypeError, ValueError):
            rejected += 1

    for conflict_day in conflicts:
        clean.pop(conflict_day, None)
    rejected += len(conflicts)

    if len(sku_values) > 1 or len(basis_values) > 1:
        return {
            "available": False,
            "reason": "样本包含不同 SKU 或价格口径，已拒绝混合预测",
            "sample_count": 0,
            "rejected_count": rejected,
            "forecast_days": horizon_days,
        }
    series = sorted(clean.items())
    if len(series) < 4:
        return {
            "available": False,
            "reason": "需至少4个不同日期的官方已核验同 SKU、同口径价格样本",
            "sample_count": len(series),
            "rejected_count": rejected,
            "forecast_days": horizon_days,
        }
    span = (series[-1][0] - series[0][0]).days
    if span < 14:
        return {
            "available": False,
            "reason": "价格样本覆盖不足14天，无法估计趋势",
            "sample_count": len(series),
            "rejected_count": rejected,
            "sample_span_days": span,
            "forecast_days": horizon_days,
        }

    # Theil-Sen median slope is less sensitive to a single erroneous snapshot than OLS.
    x = [(day - series[0][0]).days for day, _ in series]
    y = [price for _, price in series]
    pair_slopes = [
        (y[j] - y[i]) / (x[j] - x[i])
        for i in range(len(x)) for j in range(i + 1, len(x)) if x[j] != x[i]
    ]
    slope = median(pair_slopes)
    intercept = median([price - slope * day for day, price in zip(x, y)])
    target_x = x[-1] + int(horizon_days)
    predicted = max(0.0, intercept + slope * target_x)
    residuals = [price - (intercept + slope * day) for day, price in zip(x, y)]
    residual_center = median(residuals)
    mad = median([abs(value - residual_center) for value in residuals])
    band = max(1.0, 1.4826 * mad * 1.28)
    last_price = y[-1]
    change_pct = ((predicted / last_price) - 1) * 100 if last_price else 0.0
    return {
        "available": True,
        "method": "theil_sen_robust_linear_baseline",
        "forecast_days": horizon_days,
        "forecast_date": series[-1][0].fromordinal(series[-1][0].toordinal() + int(horizon_days)).isoformat(),
        "predicted_price": round(predicted, 2),
        "lower_bound": round(max(0.0, predicted - band), 2),
        "upper_bound": round(predicted + band, 2),
        "estimated_change_pct": round(change_pct, 2),
        "observed_min_price": min(y),
        "latest_observed_price": last_price,
        "sample_count": len(series),
        "rejected_count": rejected,
        "sample_span_days": span,
        "sku": next(iter(sku_values)),
        "price_basis": next(iter(basis_values)),
        "confidence": "低；稳健趋势基线，不是报价承诺",
        "limitations": [
            "模型抑制单点异常值，但不预测促销、库存、补贴、地区或账号权益",
            "最低报价必须来自授权门店价格规则；公开样本最低价不等于门店底价",
        ],
    }


def _market_price_summary(
    records: Iterable[PriceRecord], anchor: Optional[PriceRecord] = None
) -> Dict[str, object]:
    eligible = [
        item for item in records
        if item.page_price is not None
        and "已核验" in item.verification_status
        and not _blocked(item)
        and (anchor is None or (
            item.product_name == anchor.product_name
            and item.configuration == anchor.configuration
            and item.price_type == anchor.price_type
            and item.sku == anchor.sku
        ))
    ]
    if not eligible:
        return {
            "sample_lowest_public_price": None,
            "suggested_public_quote": None,
            "quote_note": "没有可核验的公开价格样本；最低成交价需按授权规则人工确认",
        }
    eligible.sort(key=lambda item: item.verified_at)
    latest = eligible[-1]
    try:
        age_days = (datetime.now().date() - datetime.strptime(latest.verified_at[:10], "%Y-%m-%d").date()).days
    except ValueError:
        age_days = None
    fresh = age_days is not None and 0 <= age_days <= 7
    return {
        "sample_lowest_public_price": min(item.page_price for item in eligible),
        "suggested_public_quote": latest.page_price if fresh else None,
        "latest_verified_public_price": latest.page_price,
        "suggested_quote_basis": "7天内最新核验的官方公开价格快照；不含门店折扣或客户权益" if fresh else "最新记录超过7天或日期无效，只作历史参考",
        "lowest_price_label": "样本最低公开价，不是门店最低成交价",
        "latest_snapshot_age_days": age_days,
        "quote_note": "四级门店价格规则未提供；公开价不得改写为授权最低报价。" + ("快照超过7天，需刷新后才能作为建议公开报价。" if not fresh else ""),
        "latest_source": latest.source_url,
        "latest_verified_at": latest.verified_at,
    }


def get_price_quality_report(records: Optional[Iterable[PriceRecord]] = None) -> Dict[str, object]:
    """Summarize source and freshness coverage; does not certify source truth."""
    pool = list(records) if records is not None else load_price_records()
    today = datetime.now().date()
    dated, stale, missing_source, amount_rows, bad_amount = 0, 0, 0, 0, 0
    for item in pool:
        if item.page_price is not None:
            amount_rows += 1
            if item.page_price <= 0:
                bad_amount += 1
        if not item.source_url:
            missing_source += 1
        try:
            age = (today - datetime.strptime(item.verified_at[:10], "%Y-%m-%d").date()).days
            dated += 1
            if age > 7:
                stale += 1
        except ValueError:
            pass
    return {
        "record_count": len(pool),
        "amount_record_count": amount_rows,
        "dated_record_count": dated,
        "stale_over_7_days_count": stale,
        "missing_source_count": missing_source,
        "invalid_amount_count": bad_amount,
        "quality_note": "自动结构检查不等于官方页面仍有效；报价前仍应复核原始来源",
    }


def _configuration_options(records: Iterable[PriceRecord], product: str) -> List[Dict[str, object]]:
    latest = {}
    for item in records:
        if item.product_name != product or item.page_price is None or "已核验" not in item.verification_status or _blocked(item):
            continue
        key = (item.configuration, item.price_type, item.sku)
        if key not in latest or item.verified_at > latest[key].verified_at:
            latest[key] = item
    return [
        {
            "configuration": item.configuration,
            "price": item.page_price,
            "price_basis": item.price_type,
            "verified_at": item.verified_at,
            "source_url": item.source_url,
        }
        for item in sorted(latest.values(), key=lambda value: value.verified_at, reverse=True)
    ]


def get_quote_status(
    product_query: str,
    customer_context: str = "",
    csv_path: Optional[Path | str] = None,
    market_price_points: Optional[Iterable[Dict[str, object]]] = None,
) -> Dict[str, object]:
    """Stable team-facing adapter; accepts externally verified market history."""
    records = load_price_records(csv_path) if csv_path else load_price_records()
    result = build_quote_status(product_query, records=records)
    payload = result.to_dict()
    matches = find_price_records(product_query, records=records, limit=len(records))
    anchor = next((item for item in matches if item.record_id == result.record_id), None)
    payload["market_price_summary"] = _market_price_summary(matches, anchor=anchor) if anchor else _market_price_summary([])
    payload["configuration_options"] = _configuration_options(matches, anchor.product_name) if anchor else []
    payload["price_data_quality"] = get_price_quality_report(records)
    payload["thirty_day_forecast"] = analyze_price_trend(market_price_points or [])
    if customer_context.strip():
        payload["customer_context"] = customer_context.strip()
    return payload


def format_quote_markdown(result: QuoteResult | Dict[str, object]) -> str:
    """Format the structured result for a Gradio Markdown output box."""
    data = result.to_dict() if isinstance(result, QuoteResult) else result
    price = data.get("public_price")
    price_text = f"¥{price:,.0f}" if isinstance(price, (int, float)) else "未提供"
    reference = data.get("reference_price")
    reference_text = f"¥{reference:,.0f}" if isinstance(reference, (int, float)) else "未提供"
    lines = [
        "### 价格与报价状态",
        f"- **产品**：{data.get('product', '待确认')}",
        f"- **具体配置**：{data.get('configuration', '待确认')}",
        f"- **公开价格**：{price_text}",
        f"- **参考/划线金额**：{reference_text}",
        f"- **价格口径**：{data.get('price_basis', '待核验')}",
        f"- **基准日期**：{data.get('baseline_date', '待核验')}",
        f"- **库存状态**：{data.get('stock_status', '待核验')}",
        f"- **来源**：[{data.get('source_title', '暂无来源')}]({data.get('source_url', '')})",
        f"- **报价状态**：{data.get('status_label', '待人工核验')}",
        "\n**市场参考**：",
    ]
    summary = data.get("market_price_summary", {})
    low = summary.get("sample_lowest_public_price")
    suggested = summary.get("suggested_public_quote")
    latest_public = summary.get("latest_verified_public_price")
    lines.append(f"- 样本最低公开价：{f'¥{low:,.0f}' if isinstance(low, (int, float)) else '暂无'}（不是门店底价）")
    lines.append(f"- 建议公开报价参考：{f'¥{suggested:,.0f}' if isinstance(suggested, (int, float)) else '暂无（快照过期或数据不足）'}")
    if isinstance(latest_public, (int, float)) and suggested is None:
        lines.append(f"- 最近历史公开价：¥{latest_public:,.0f}（仅历史参考）")
    lines.append(f"- 说明：{summary.get('quote_note', '需人工核验')}")
    options = data.get("configuration_options", [])
    if options:
        lines.append("- 同产品其他已核验配置：")
        lines.extend(
            f"  - {item['configuration']}：¥{item['price']:,.0f}（{item['price_basis']}，{item['verified_at'][:10]}）"
            for item in options[:5]
        )
    quality = data.get("price_data_quality", {})
    if quality:
        lines.append(
            f"- 数据检查：{quality.get('record_count', 0)}条记录，"
            f"{quality.get('stale_over_7_days_count', 0)}条超过7天；"
            f"缺来源{quality.get('missing_source_count', 0)}条"
        )
    forecast = data.get("thirty_day_forecast", {})
    if forecast.get("available"):
        lines.append(
            f"- 30天趋势基线：¥{forecast['predicted_price']:,.0f} "
            f"（区间 ¥{forecast['lower_bound']:,.0f}–¥{forecast['upper_bound']:,.0f}；低置信度）"
        )
    else:
        lines.append(f"- 30天价格预测：不可用，{forecast.get('reason', '缺少历史样本')}")
    lines.append("\n**待人工核验项**：")
    lines.extend(f"- {item}" for item in data.get("manual_review_items", []))
    if data.get("evidence"):
        lines.append(f"\n**证据摘要**：{data['evidence']}")
    return "\n".join(lines)


if __name__ == "__main__":
    demo = get_quote_status("HUAWEI MateBook 14（鸿蒙版）")
    print(format_quote_markdown(demo))
