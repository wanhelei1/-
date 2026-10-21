"""Deterministic, evidence-backed three-minute in-store demo script drafts.

The script is a structured coaching aid, not an LLM-generated or customer-tested
sales script. Product claims are copied from public product fact files and carry
relative paths and line numbers. Unknown compatibility and commercial terms stay
as questions for human verification.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

DEFAULT_KB = (
    Path(__file__).resolve().parents[2]
    / "knowledge-base"
    / "华为PC全板块深度知识库_v7"
)

DURATION_PLAN = (
    ("opening", "开场", 20),
    ("need_confirmation", "需求确认", 35),
    ("product_demo", "产品演示", 75),
    ("objection_handling", "异议处理", 35),
    ("close", "收口", 15),
)
FACT_PATTERN = re.compile(
    r"(?:\d+(?:\.\d+)?\s*(?:mm|毫米|kg|千克|英寸|GB|TB|Hz|nits|PPI|W|瓦|小时|点|°)|"
    r"HarmonyOS\s*\d*|Windows\s*\d*|OLED|LCD|Wi-?Fi|蓝牙|麒麟|酷睿|锐龙|"
    r"支持|搭载|采用|配备|内置|提供)",
    re.IGNORECASE,
)
SKIP_FACT = ("实际", "可能", "请以", "温馨提示", "免责声明", "来源：", "抓取日期")
_SOURCE_HEADING_PATTERN = re.compile(r"(?:来源|参考链接|资料链接|source|reference)", re.IGNORECASE)
_URL_PATTERN = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
RELEVANCE_TERMS = {
    "屏幕": ("屏幕", "显示", "色彩", "触控", "阅读", "设计"),
    "便携": ("重量", "厚度", "尺寸", "通勤", "携带", "出差", "便携"),
    "软件": ("系统", "操作系统", "软件", "应用", "兼容"),
    "性能": ("处理器", "cpu", "显卡", "内存", "存储", "性能", "剪辑", "建模"),
    "连接": ("接口", "连接", "端口", "usb", "hdmi", "外设", "扩展坞"),
    "学习": ("屏幕", "重量", "内存", "存储", "键盘", "网课", "学习"),
    "创作": ("屏幕", "处理器", "内存", "存储", "色域", "创作", "剪辑"),
}


def _clean(value: Any, limit: int = 500) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())[:limit]


def _resolve_facts_file(product: str, knowledge_base_dir: Path) -> Path | None:
    product_root = knowledge_base_dir / "P1-产品参数库"
    if not product_root.is_dir():
        return None
    query = product.casefold().strip()
    files = sorted(product_root.rglob("产品事实.md"))
    exact = [path for path in files if path.parent.name.casefold() == query]
    if exact:
        return exact[0]
    matches = [
        path for path in files
        if path.parent.name.casefold() in query or query in path.parent.name.casefold()
    ]
    return max(matches, key=lambda path: len(path.parent.name)) if matches else None


def _is_source_heading(text: str) -> bool:
    return bool(_SOURCE_HEADING_PATTERN.search(text))


def _label_for(lines: list[str], index: int, headings: list[str]) -> str:
    previous = index - 1
    while previous >= 0 and not lines[previous].strip():
        previous -= 1
    label = ""
    if previous >= 0:
        candidate = re.sub(r"^\s*[-*+]\s*|\s*[*`]", "", lines[previous]).strip()
        candidate = candidate.rstrip(":：")
        if (
            candidate
            and len(candidate) <= 32
            and not candidate.startswith("#")
            and not _URL_PATTERN.search(candidate)
            and not _is_source_heading(candidate)
            and not re.search(r"[。！？；]$", candidate)
            and not FACT_PATTERN.search(candidate)
        ):
            label = candidate
    section = headings[-1] if headings else ""
    if _is_source_heading(section):
        section = ""
    if label and section and label != section:
        return f"{section} · {label}"
    return label or section


def _extract_facts(path: Path, need_text: str, limit: int = 3) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    headings: list[str] = []
    candidates: list[tuple[int, dict[str, Any]]] = []
    query = need_text.casefold()
    relevance = [term for terms in RELEVANCE_TERMS.values() for term in terms if term in query]

    for index, raw in enumerate(lines):
        heading = re.match(r"^\s*(#{1,6})\s+(.+?)\s*$", raw)
        if heading:
            level = len(heading.group(1))
            headings = headings[: level - 1]
            headings.append(heading.group(2).strip())
            continue
        text = re.sub(r"^\s*[-*+]\s+", "", raw).strip()
        if (
            not text
            or text.startswith(("[", ">", "|", "!"))
            or _URL_PATTERN.search(text)
            or any(_is_source_heading(item) for item in headings)
            or any(word in text for word in SKIP_FACT)
        ):
            continue
        if not FACT_PATTERN.search(text) or len(text) > 180:
            continue
        label = _label_for(lines, index, headings)
        claim = f"{label}：{text}" if label and label.casefold() not in text.casefold() else text
        lowered = f"{label} {text}".casefold()
        score = sum(2 for term in relevance if term.casefold() in lowered)
        if re.search(r"(?:HarmonyOS|Windows|OLED|Wi-?Fi|麒麟|酷睿)", text, re.IGNORECASE):
            score += 1
        candidates.append((score, {
            "claim": claim,
            "source": path.relative_to(knowledge_base_root(path)).as_posix(),
            "line_start": index + 1,
            "line_end": index + 1,
        }))

    candidates.sort(key=lambda item: (-item[0], item[1]["line_start"]))
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, fact in candidates:
        normalized = fact["claim"].casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        selected.append(fact)
        if len(selected) == limit:
            break
    return selected


def knowledge_base_root(path: Path) -> Path:
    """Return the parent suitable for stable knowledge-base-relative citations."""
    for parent in path.parents:
        if parent.name == "华为PC全板块深度知识库_v7":
            return parent.parent
    return path.parent


def _objection_response(objection: str) -> tuple[str, str]:
    text = objection.casefold()
    if any(word in text for word in ("预算", "价格", "贵", "费用", "优惠")):
        return (
            "价格与预算",
            "我理解您在意总预算。当前资料不能代表门店实时成交价或活动资格；我们先确认完整 SKU、地区和预算范围，再请授权人员核对当日价格与权益。",
        )
    if any(word in text for word in ("软件", "兼容", "系统", "应用", "外设", "驱动")):
        return (
            "软件与兼容",
            "这个顾虑需要按具体软件或外设的名称、版本和使用任务核实。我不会先承诺兼容；我们可以查官方要求，并在目标环境用您的实际任务验证。",
        )
    if any(word in text for word in ("性能", "卡顿", "剪辑", "建模", "游戏", "配置")):
        return (
            "性能与配置",
            "我们先把项目规模、软件版本和同时运行的任务列清，再核对这台具体配置的依据；能否满足，以您的代表性任务现场测试为准。",
        )
    if any(word in text for word in ("重量", "续航", "携带", "出差", "通勤")):
        return (
            "携带与使用体验",
            "我们可以先核对该 SKU 的官方重量与规格，再把充电器和常用外设一并考虑；续航和手感建议按您的实际使用方式现场体验。",
        )
    if objection:
        return (
            "待澄清顾虑",
            f"我先确认一下，您主要担心的是“{objection}”里的哪一部分？我们把问题拆成可核对的配置、来源或现场测试，不在证据不足时先作保证。",
        )
    return (
        "开放异议",
        "您还有哪一点不放心？我先把顾虑记准确，再一起确认它需要查资料、核对具体配置，还是现场实测；没有验证前不作保证。",
    )


def generate_demo_script(
    payload: Mapping[str, Any],
    knowledge_base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Return a five-part, 180-second customer-facing demo script draft."""
    if not isinstance(payload, Mapping):
        raise ValueError("请求内容必须是对象")

    product = _clean(payload.get("product"), 160)
    task = _clean(payload.get("customer_task") or payload.get("need") or payload.get("needs"), 500)
    persona = _clean(payload.get("persona") or payload.get("customer_type"), 100)
    scene = _clean(payload.get("scenario") or payload.get("usage_scenario"), 120)
    concern = _clean(payload.get("objection") or payload.get("concern") or payload.get("priority_concern"), 240)
    software = _clean(payload.get("required_software"), 240)
    peripherals = _clean(payload.get("peripherals"), 240)
    root = Path(knowledge_base_dir or DEFAULT_KB).expanduser().resolve()

    facts_path = _resolve_facts_file(product, root) if product else None
    facts = _extract_facts(facts_path, " ".join((task, scene, concern))) if facts_path else []
    topic, response = _objection_response(concern)
    product_display = product or "待确认具体产品型号"
    task_display = f"{task}。" if task else "您最希望电脑帮您完成的具体任务。"
    evidence_lines = [f"{fact['claim']}（{fact['source']}:{fact['line_start']}）" for fact in facts]
    if evidence_lines:
        demo_talk = (
            f"这次我们看的是 {product_display}。结合您刚才说的“{task or '使用需求'}”，"
            "我只展示有资料依据、且和当前任务相关的部分："
            + "；".join(evidence_lines)
            + "。这些是产品资料摘录，销售 SKU 和配置仍需逐项确认。"
        )
    elif product:
        demo_talk = (
            f"这次我们先围绕 {product_display} 做任务演示。目前没有找到可引用的产品事实摘录，"
            "所以我不先口述未经核实的参数；请以实际产品资料为准，再邀请您用自己的代表性任务体验。"
        )
    else:
        demo_talk = (
            "产品型号尚未确定，本段先不陈述产品参数。确认具体型号和销售配置后，再从对应官方事实资料中挑选与任务相关的项目演示。"
        )

    opening = (
        f"您好，{persona + '，' if persona else ''}我想用大约三分钟，围绕“{task or '您当前最重要的使用任务'}”看一遍。"
        "我先复述需求，您随时纠正；涉及价格、兼容或体验的部分，我们以核验和实测为准。"
    )
    need_questions = [
        f"我理解您主要想完成：{task_display}我复述得准确吗？",
        f"使用场景是“{scene}”吗？最不能出问题的一步是什么？" if scene else "主要在哪些场景使用？最不能出问题的一步是什么？",
        f"必须使用的软件/版本是“{software}”吗？" if software else "有必须使用的软件及具体版本吗？",
        f"需要连接的外设是“{peripherals}”吗？" if peripherals else "还要连接哪些外设或遵守哪些系统要求？",
    ]
    objection_title, objection_response = _objection_response(concern)
    close = (
        "今天先确认了需求，并把需要依据支持的部分和仍待核验的部分分开。"
        "如果您觉得合适，下一步我们可以核对完整 SKU，再用您的代表性任务和必需外设现场试一次；"
        "价格、库存、兼容性和活动由授权人员按当日情况确认。"
    )

    sections = [
        {
            "id": "opening", "title": "开场", "duration_seconds": 20,
            "goal": "说明演示范围并取得顾客纠正或补充的机会。",
            "say": opening, "actions": ["面向顾客说明演示约三分钟。", "先复述已提供的任务，不补写顾客需求。"],
            "evidence": [],
        },
        {
            "id": "need_confirmation", "title": "需求确认", "duration_seconds": 35,
            "goal": "确认任务、场景与必须验证的门槛。",
            "say": "\n".join(need_questions),
            "actions": ["逐项确认顾客原话。", "将未提供的软件版本和外设型号记为待确认。"],
            "evidence": [],
        },
        {
            "id": "product_demo", "title": "产品演示", "duration_seconds": 75,
            "goal": "围绕顾客任务展示可追溯的产品事实，并安排真实任务体验。",
            "say": demo_talk,
            "actions": [
                "按引用的事实资料展示对应设置或硬件位置；不把一个配置的事实泛化到所有 SKU。",
                "邀请顾客亲自完成一项代表性任务；记录测试环境、版本、结果和限制。",
                "软件、外设与组织策略兼容性未验证前保持待确认。",
            ],
            "evidence": facts,
        },
        {
            "id": "objection_handling", "title": "异议处理", "duration_seconds": 35,
            "goal": "先澄清顾虑，再给出可验证的处理动作，不作无依据承诺。",
            "topic": objection_title,
            "customer_objection": concern or "顾客的具体顾虑尚未记录。",
            "say": objection_response,
            "actions": ["先确认顾客是否认可对顾虑的复述。", "约定所需的资料核验或现场测试。"],
            "evidence": [],
        },
        {
            "id": "close", "title": "收口", "duration_seconds": 15,
            "goal": "总结已确认事项和下一步，不制造紧迫感。",
            "say": close,
            "actions": ["征求顾客是否愿意进行下一步核验或体验。", "记录待办，不代替顾客作购买决定。"],
            "evidence": [],
        },
    ]
    return {
        "schema_version": 1,
        "status": "ready" if facts else ("needs_product" if not product else "limited_evidence"),
        "duration_seconds": sum(section["duration_seconds"] for section in sections),
        "product": product or None,
        "customer_context": {
            "persona": persona,
            "scenario": scene,
            "customer_task": task,
            "concern": concern,
            "required_software": software,
            "peripherals": peripherals,
        },
        "sections": sections,
        "guardrails": [
            "这是确定性规则生成的可编辑话术草稿，不是大模型输出或实测销售效果。",
            "产品事实附知识库相对路径和行号；请核对完整销售 SKU 与资料时效。",
            "不承诺实时成交价、库存、优惠、软件兼容性或未经验证的体验结果。",
            "不得录入顾客姓名、手机号、账号等身份或敏感信息。",
        ],
    }


def format_demo_script(script: Mapping[str, Any]) -> str:
    """Render a generated script as plain text for copying or review."""
    lines = [f"3 分钟顾客演示脚本｜{script.get('product') or '待确认产品'}"]
    for section in script.get("sections", []):
        lines.extend([
            "",
            f"【{section['title']} · {section['duration_seconds']} 秒】",
            str(section.get("say", "")),
        ])
        for fact in section.get("evidence", []):
            lines.append(f"依据：{fact['claim']}（{fact['source']}:{fact['line_start']}）")
    return "\n".join(lines)
