"""门店增长智能体：可核验价格与报价状态模块。

本模块只处理价格事实，不计算未授权的门店折扣、补贴或成交价。
队友接入方式：
    from pricing_module import get_quote_status
    result = get_quote_status("HUAWEI MateBook 14（鸿蒙版）", "预算6000元")

返回值是可直接序列化为 JSON 的 dict，不依赖第三方包。
"""

from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from statistics import median
from urllib.parse import urlparse
from pathlib import Path
from typing import Dict, Iterable, List, Optional


DEFAULT_CSV = (
    Path(__file__).resolve().parent
    / "knowledge-base"
    / "华为PC全板块深度知识库_v7"
    / "P1-产品参数库"
    / "08-官方公开价格快照"
    / "官方价格快照.csv"
)

# 只有明确出现这些状态时，才阻止展示金额；不凭空推断库存或成交状态。
BLOCKED_STATUS_WORDS = ("下架", "未公开", "无当前公开", "官方询价")


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
    )


def load_price_records(csv_path: Optional[Path | str] = None) -> List[PriceRecord]:
    """Load the official snapshot CSV. Missing data raises a clear local error."""
    path = Path(csv_path) if csv_path else DEFAULT_CSV
    if not path.exists():
        raise FileNotFoundError(
            f"找不到价格快照：{path}\n"
            "请确认知识库已解压到 pricing_module.py 同级的 knowledge-base 目录。"
        )
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [_record(row) for row in csv.DictReader(handle)]


def _match_score(record: PriceRecord, query: str) -> int:
    terms = [part for part in re.split(r"\s+|[，,、;；/]+", query.strip()) if part]
    haystack = " ".join(
        [record.product_name, record.original_name, record.configuration, record.sku]
    ).lower()
    return sum(1 for term in terms if term.lower() in haystack)


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


def build_quote_status(product_query: str, records: Optional[Iterable[PriceRecord]] = None) -> QuoteResult:
    """Build one safe quote result for the team app.

    A public snapshot amount is shown only when it is present, verified, and not
    explicitly blocked by the source status. The result still carries manual
    review items because the P4 four-level store pricing data is unavailable.
    """
    matches = find_price_records(product_query, records=records)
    record = next(
        (
            item
            for item in matches
            if item.page_price is not None
            and "已核验" in item.verification_status
            and not _blocked(item)
        ),
        None,
    )

    if record is None:
        fallback = matches[0] if matches else None
        return QuoteResult(
            product=fallback.product_name if fallback else product_query.strip(),
            configuration=fallback.configuration if fallback else "待确认具体配置",
            public_price=None,
            reference_price=fallback.reference_price if fallback else None,
            currency="CNY",
            price_basis=fallback.price_type if fallback else "暂无可核验公开价格",
            baseline_date=_date_only(fallback.verified_at) if fallback else "待核验",
            source_title=fallback.source_title if fallback else "暂无来源",
            source_url=fallback.source_url if fallback else "",
            stock_status=fallback.stock_status if fallback else "待核验",
            status="manual_review",
            status_label="待人工核验，暂不输出具体成交价",
            manual_review_items=_manual_items(fallback),
            evidence=fallback.evidence if fallback else "知识库中未找到可用价格证据",
            record_id=fallback.record_id if fallback else "",
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
