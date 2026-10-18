"""第七块 · 依据与合规（纯函数模块，无网络 / 无文件 IO / 无第三方依赖）。

输出三部分：
  1. 已引用来源：事实 F*、图片 I* 的来源清单（标题、知识库路径、直链、用在何处）
  2. 检测到的风险：绝对化、价格促销、无依据对比、虚构体验、贬低竞品/虚假承诺
  3. 待人工确认项：来源缺失、型号不一致、文案出现事实之外的数字等

对外只需一个入口：

    from block07_compliance import build_evidence_section
    section = build_evidence_section(facts=facts, images=images, copy=copy, task=task)
    st.markdown(section["markdown"])

兼容 CONTRACT.md 的 facts / images / copy 结构，也兼容纯字符串列表。
Python 3.10+，只用标准库。
"""

from __future__ import annotations

import re
from typing import Any, Iterable

SECTION_TITLE = "## 七、依据与合规"

# ---------------------------------------------------------------- 规则库

# 绝对化用语：逐词匹配，避免“最近/最终”这类误伤
ABSOLUTE_TERMS = [
    "最好", "最佳", "最强", "最大", "最轻", "最薄", "最快", "最全", "最先进",
    "最便宜", "第一", "唯一", "顶级", "极致", "100%", "百分之百", "绝对",
    "永久", "终身", "万能", "无敌", "史上", "全球首", "国家级", "遥遥领先",
]

# 价格与促销：命中即高风险，价格政策不在知识库可引用范围
PRICE_TERMS = [
    "免费", "0元", "零元", "白送", "直降", "立减", "补贴", "到手价", "秒杀",
    "库存告急", "最后一批", "限时", "特价", "优惠价", "骨折价", "返现",
]
PRICE_PATTERNS = [
    r"直降\s*\d+", r"立减\s*\d+", r"减\s*\d+\s*元", r"只要\s*\d+",
    r"低至\s*\d+", r"\d+\s*元起", r"最后\s*\d+\s*台",
]

# 无依据对比：结论性比较，必须有知识库依据才允许
COMPARE_TERMS = ["吊打", "碾压", "完爆", "秒杀", "全面超越", "完全超越", "不如", "遥遥领先"]
COMPARE_PATTERNS = [r"比[^。；\n]{0,12}(好|强|快|轻|薄|便宜)"]

# 虚构体验：伪造个人使用经历
EXPERIENCE_TERMS = ["亲测", "实测", "真实体验", "我用了", "入手了"]
EXPERIENCE_PATTERNS = [
    r"用了\s*\d+\s*(天|周|个月|年)", r"入手\s*\d+\s*(天|周|个月|年)",
    r"上手\s*\d+\s*(天|周|个月|年)", r"第\s*\d+\s*天",
]

# 贬低竞品 / 虚假承诺
DISPARAGE_TERMS = ["垃圾", "智商税", "割韭菜", "翻车", "坑人", "保证", "承诺",
                   "终身保修", "100%满意", "无效退款", "假一赔十"]

ATOM_RE = re.compile(r"[^。！？；\n]+[。！？；]?")

TYPE_ABSOLUTE = "绝对化用语"
TYPE_PRICE = "虚假价格与促销"
TYPE_COMPARE = "无依据对比"
TYPE_EXPERIENCE = "虚构体验"
TYPE_DISPARAGE = "贬低竞品与虚假承诺"

# ---------------------------------------------------------------- 工具函数


def _norm(text: str) -> str:
    """全角转半角、去多余空白、转小写，便于匹配。"""
    if not isinstance(text, str):
        return ""
    out = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return re.sub(r"\s+", " ", "".join(out)).strip().lower()


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in ATOM_RE.findall(text or "") if s.strip()]


def _copy_fields(copy: Any) -> list[tuple[str, str]]:
    """把 copy 拆成 (位置, 文本)，兼容 dict / str / None。"""
    if not copy:
        return []
    if isinstance(copy, str):
        return [("文案", copy)]
    labels = [
        ("title", "标题"),
        ("lead", "导语"),
        ("body", "正文"),
        ("cta", "行动引导"),
        ("hashtags", "话题标签"),
    ]
    fields: list[tuple[str, str]] = []
    for key, label in labels:
        value = copy.get(key)
        if isinstance(value, str) and value.strip():
            fields.append((label, value))
        elif isinstance(value, (list, tuple)):
            text = " ".join(str(v) for v in value if v)
            if text.strip():
                fields.append((label, text))
    return fields


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _risk(level: str, kind: str, matched: str, advice: str, where: str) -> dict:
    return {
        "level": level,
        "type": kind,
        "matched": matched,
        "advice": advice,
        "where": where,
    }


# ---------------------------------------------------------------- 7.1 已引用来源


def build_sources(facts: Any = None, images: Any = None) -> list[dict]:
    """汇总事实与图片来源，按编号去重。"""
    sources: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for index, fact in enumerate(_as_list(facts), start=1):
        if isinstance(fact, str):
            fact = {"id": f"F{index}", "claim": fact}
        if not isinstance(fact, dict):
            continue
        ref = str(fact.get("fact_id") or fact.get("id") or f"F{index}")
        title = str(fact.get("source_title") or "").strip()
        path = str(fact.get("source_path") or "").strip()
        url = str(fact.get("source_url") or "").strip()
        claim = str(fact.get("claim") or "").strip()
        key = ("fact", ref)
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "ref": ref,
            "kind": "事实",
            "title": title or "（缺标题）",
            "path": path,
            "url": url,
            "summary": claim[:80],
        })

    for index, image in enumerate(_as_list(images), start=1):
        if isinstance(image, str):
            image = {"id": f"I{index}", "name": image}
        if not isinstance(image, dict):
            continue
        ref = str(image.get("image_id") or image.get("id") or f"I{index}")
        name = str(image.get("name") or "").strip()
        title = str(image.get("title") or name or "（未命名图片）").strip()
        url = str(image.get("url") or image.get("source") or "").strip()
        model = str(image.get("model") or "").strip()
        position = str(image.get("position_hint") or "").strip()
        key = ("image", ref)
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "ref": ref,
            "kind": "图片",
            "title": title,
            "path": model,
            "url": url,
            "summary": f"{name}{('，' + position) if position else ''}",
        })

    return sources


# ---------------------------------------------------------------- 7.2 检测到的风险


def detect_risks(copy: Any = None, text: str = "") -> list[dict]:
    """扫描文案，返回风险列表；同一位置同一类型只报一次。"""
    fields = _copy_fields(copy)
    if not fields and text:
        fields = [("文案", text)]

    risks: list[dict] = []
    index: dict[tuple[str, str], int] = {}

    def add(level: str, kind: str, matched: str, advice: str, where: str) -> None:
        """同一位置同一类型只保留最具体的一条（matched 更长者胜）。"""
        key = (kind, where)
        position = index.get(key)
        if position is None:
            index[key] = len(risks)
            risks.append(_risk(level, kind, matched, advice, where))
        elif len(matched) > len(risks[position]["matched"]):
            risks[position] = _risk(level, kind, matched, advice, where)

    for where, value in fields:
        norm = _norm(value)
        for term in ABSOLUTE_TERMS:
            if _norm(term) in norm:
                add("高", TYPE_ABSOLUTE, term,
                    "删除绝对化表述，改成可核验的具体事实", where)
        for term in PRICE_TERMS:
            if _norm(term) in norm:
                add("高", TYPE_PRICE, term,
                    "价格/促销不在可引用范围，改为“以官方渠道实时信息为准”", where)
        for pattern in PRICE_PATTERNS:
            match = re.search(pattern, norm)
            if match:
                add("高", TYPE_PRICE, match.group(0),
                    "删除具体优惠数字，改由门店或官网确认", where)
        for term in COMPARE_TERMS:
            if _norm(term) in norm:
                add("中", TYPE_COMPARE, term,
                    "只保留有知识库依据的参数对比，不做优劣结论", where)
        for pattern in COMPARE_PATTERNS:
            match = re.search(pattern, norm)
            if match:
                add("中", TYPE_COMPARE, match.group(0),
                    "补充对比依据或删除比较结论", where)
        for term in EXPERIENCE_TERMS:
            if _norm(term) in norm:
                add("中", TYPE_EXPERIENCE, term,
                    "删除个人体验表述，改为产品事实", where)
        for pattern in EXPERIENCE_PATTERNS:
            match = re.search(pattern, norm)
            if match:
                add("中", TYPE_EXPERIENCE, match.group(0),
                    "不得虚构使用天数，改为场景化描述", where)
        for term in DISPARAGE_TERMS:
            if _norm(term) in norm:
                add("高", TYPE_DISPARAGE, term,
                    "删除贬低与承诺类表述，避免不正当竞争与虚假承诺", where)

    return risks


# ---------------------------------------------------------------- 7.3 待人工确认


def _fact_claims(facts: Any) -> str:
    parts: list[str] = []
    for fact in _as_list(facts):
        if isinstance(fact, dict):
            parts.append(str(fact.get("claim") or ""))
        else:
            parts.append(str(fact))
    return _norm(" ".join(parts))


def collect_pending(
    facts: Any = None,
    images: Any = None,
    copy: Any = None,
    product: str = "",
) -> list[str]:
    """列出需要人工确认的事项。"""
    pending: list[str] = []
    fact_list = [f for f in _as_list(facts) if isinstance(f, (dict, str))]
    image_list = [i for i in _as_list(images) if isinstance(i, (dict, str))]

    if not fact_list:
        pending.append("知识库未检索到足够事实，正文不得生成")
    if not image_list:
        pending.append("未检索到本型号图片，配图方案需人工补充")

    for index, fact in enumerate(fact_list, start=1):
        if not isinstance(fact, dict):
            pending.append(f"F{index} 为纯文本事实，缺少来源标题与路径")
            continue
        ref = fact.get("fact_id") or fact.get("id") or f"F{index}"
        if not str(fact.get("source_title") or "").strip():
            pending.append(f"{ref} 缺少来源标题")
        if not str(fact.get("source_path") or "").strip():
            pending.append(f"{ref} 缺少知识库路径")

    for index, image in enumerate(image_list, start=1):
        if not isinstance(image, dict):
            pending.append(f"I{index} 为纯文本图片，缺少型号与直链")
            continue
        ref = image.get("image_id") or image.get("id") or f"I{index}"
        if not str(image.get("url") or "").strip():
            pending.append(f"{ref} 缺少图片直链，需人工核验")
        model = str(image.get("model") or "").strip()
        if product and model and _norm(model) not in _norm(product) and _norm(product) not in _norm(model):
            pending.append(f"{ref} 型号「{model}」与当前产品「{product}」不一致，不得使用")
        if not model:
            pending.append(f"{ref} 未标注所属型号，需人工确认")

    text_all = " ".join(value for _, value in _copy_fields(copy))
    if text_all:
        norm = _norm(text_all)
        if any(_norm(t) in norm for t in PRICE_TERMS) or any(
            re.search(p, norm) for p in PRICE_PATTERNS
        ):
            pending.append("文案涉及价格或促销，发布前需门店/官方渠道确认")
        claims = _fact_claims(facts)
        for _, value in _copy_fields(copy):
            if any(item.startswith("句子含未在事实清单出现的数字") for item in pending):
                break
            for sentence in _sentences(value):
                numbers = re.findall(r"\d+(?:\.\d+)?", sentence)
                if not numbers:
                    continue
                missing = [n for n in numbers if n not in claims]
                if missing:
                    pending.append(
                        f"句子含未在事实清单出现的数字 {missing}：「{sentence[:30]}」"
                    )
                    break

    # 去重保序
    unique: list[str] = []
    for item in pending:
        if item not in unique:
            unique.append(item)
    return unique


# ---------------------------------------------------------------- 渲染


def render_markdown(
    sources: Iterable[dict],
    risks: Iterable[dict],
    pending: Iterable[str],
    product: str = "",
) -> str:
    lines: list[str] = [SECTION_TITLE, ""]
    if product:
        lines.append(f"> 当前产品：{product}")
        lines.append("")

    lines.append("### 已引用来源")
    lines.append("")
    source_list = list(sources)
    if source_list:
        lines.append("| 编号 | 类型 | 标题 | 知识库位置 / 型号 | 链接 |")
        lines.append("|---|---|---|---|---|")
        for item in source_list:
            title = str(item.get("title") or "").replace("|", "\\|")
            path = str(item.get("path") or "").replace("|", "\\|") or "—"
            url = str(item.get("url") or "").strip()
            link = f"[原文]({url})" if url else "—"
            lines.append(f"| {item.get('ref', '')} | {item.get('kind', '')} | {title} | {path} | {link} |")
    else:
        lines.append("暂无已引用来源（未检索到事实或图片）。")
    lines.append("")

    lines.append("### 检测到的风险")
    lines.append("")
    risk_list = list(risks)
    if risk_list:
        for risk in risk_list:
            lines.append(
                f"- **{risk['level']}** · {risk['type']} · {risk['where']}："
                f"「{risk['matched']}」→ {risk['advice']}"
            )
    else:
        lines.append("未检测到绝对化用语、虚假价格、无依据对比、虚构体验等风险。")
    lines.append("")

    lines.append("### 待人工确认项")
    lines.append("")
    pending_list = list(pending)
    if pending_list:
        for item in pending_list:
            lines.append(f"- {item}")
    else:
        lines.append("无。")

    return "\n".join(lines).strip()


# ---------------------------------------------------------------- 对外入口


def build_evidence_section(
    facts: Any = None,
    images: Any = None,
    copy: Any = None,
    task: dict | None = None,
    product: str = "",
    extra_pending: Iterable[str] | None = None,
) -> dict:
    """生成第七块：来源、风险、待确认项与 Markdown。

    facts / images / copy 可直接传 CONTRACT.md 的结构；
    product 可从 task["product"] 自动取，也可显式传。
    """
    if not product and isinstance(task, dict):
        product = str(task.get("product") or "")

    sources = build_sources(facts, images)
    risks = detect_risks(copy)
    pending = collect_pending(facts, images, copy, product)
    for item in extra_pending or []:
        text = str(item).strip()
        if text and text not in pending:
            pending.append(text)

    high = sum(1 for risk in risks if risk["level"] == "高")
    return {
        "product": product,
        "sources": sources,
        "risks": risks,
        "pending": pending,
        "stats": {
            "source_count": len(sources),
            "risk_count": len(risks),
            "high_risk": high,
            "pending_count": len(pending),
        },
        "passed": not risks and not pending,
        "markdown": render_markdown(sources, risks, pending, product),
    }


def analyze_text(text: str) -> dict:
    """只做合规检测的便捷入口（用于输入框实时提示）。"""
    risks = detect_risks(text=text)
    return {
        "passed": not risks,
        "risk_level": "高" if any(r["level"] == "高" for r in risks) else ("中" if risks else "低"),
        "risks": risks,
    }


def build_from_output(
    output: dict | None = None,
    facts: Any = None,
    images: Any = None,
    task: dict | None = None,
    product: str = "",
) -> dict:
    """从 CONTRACT 1.5 的完整 output 直接生成第七块。

    output 形如：
      {"copy": {...}, "evidence": [...], "images": [...],
       "verification": {"pending": [...]}, ...}

    传了 facts / images 时以显式参数为准，否则回退用 output 里的内容。
    """
    output = output or {}
    copy = output.get("copy") or {}
    if facts is None:
        facts = output.get("evidence") or []
    if images is None:
        images = output.get("images") or []
    verification = output.get("verification") or {}
    extra = verification.get("pending") or []
    return build_evidence_section(
        facts=facts,
        images=images,
        copy=copy,
        task=task,
        product=product,
        extra_pending=extra,
    )
