from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KB = _PROJECT_ROOT / "knowledge-base" / "华为PC全板块深度知识库_v7"
EXCLUDED_PARTS = {"P4-价格政策库（机密）", "90-待审核", "99-历史归档", "09-来源研究底稿"}
TEXT_SUFFIXES = {".md", ".csv", ".json"}
PRODUCT_DIRS = (
    Path("P1-产品参数库/01-鸿蒙电脑"),
    Path("P1-产品参数库/02-MateBook-Windows"),
)


@dataclass(frozen=True)
class Chunk:
    text: str
    source: str
    title: str


def _tokens(text: str) -> set[str]:
    text = text.lower()
    tokens = set(re.findall(r"[a-z0-9][a-z0-9.+-]*", text))
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        if len(run) <= 2:
            tokens.add(run)
        else:
            tokens.update(run[i : i + 2] for i in range(len(run) - 1))
            tokens.add(run)
    return tokens


def _read_text(path: Path) -> str:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = csv.reader(stream)
            return "\n".join(" | ".join(cell.strip() for cell in row if cell.strip()) for row in rows)
    if path.suffix.lower() == ".json":
        with path.open("r", encoding="utf-8-sig") as stream:
            return json.dumps(json.load(stream, strict=False), ensure_ascii=False, indent=2)
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _chunks(text: str, source: str, title: str, size: int = 850) -> Iterable[Chunk]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    buffer = ""
    for paragraph in paragraphs:
        if len(paragraph) > size:
            if buffer:
                yield Chunk(buffer, source, title)
                buffer = ""
            for start in range(0, len(paragraph), size - 120):
                yield Chunk(paragraph[start : start + size], source, title)
        elif len(buffer) + len(paragraph) + 2 > size:
            yield Chunk(buffer, source, title)
            buffer = paragraph
        else:
            buffer = f"{buffer}\n\n{paragraph}" if buffer else paragraph
    if buffer:
        yield Chunk(buffer, source, title)


class KnowledgeBase:
    def __init__(self, root: Path | str = DEFAULT_KB):
        self.root = Path(root).expanduser().resolve()
        self.chunks: list[Chunk] = []
        self.product_files: list[tuple[str, str]] = []
        self.file_count = 0
        self.load_errors: list[str] = []
        self._load()

    def _is_excluded(self, path: Path) -> bool:
        return any(part in EXCLUDED_PARTS for part in path.parts)

    def _load(self) -> None:
        if not self.root.is_dir():
            raise FileNotFoundError(f"找不到知识库目录：{self.root}")
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES or self._is_excluded(path.relative_to(self.root)):
                continue
            relative = path.relative_to(self.root)
            if "08-官方公开价格快照" in relative.parts:
                continue
            try:
                text = _read_text(path)
            except (OSError, UnicodeError, json.JSONDecodeError, csv.Error) as exc:
                self.load_errors.append(f"{relative}: {exc}")
                continue
            if not text.strip():
                continue
            self.file_count += 1
            title = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("# ")), path.stem)
            self.chunks.extend(_chunks(text, relative.as_posix(), title))
            if path.name == "产品事实.md" and relative.parts[0] == "P1-产品参数库":
                self.product_files.append((relative.as_posix(), text))

    def search(self, query: str, limit: int = 6) -> list[tuple[float, Chunk]]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        ranked = []
        for chunk in self.chunks:
            body = _tokens(chunk.text)
            common = query_tokens & body
            if not common:
                continue
            score = sum(1.0 if len(token) < 3 else 1.4 for token in common)
            score += min(len(common), 10) * 0.12
            if "产品事实.md" in chunk.source:
                score *= 1.12
            if "P8-客户场景库" in chunk.source and any(k in query for k in ("学生", "出差", "办公", "设计", "老师", "销售", "家庭", "剪辑")):
                score *= 1.15
            ranked.append((score, chunk))
        ranked.sort(key=lambda pair: (pair[0], len(pair[1].text)), reverse=True)
        return ranked[:limit]


def _profile(query: str) -> tuple[list[str], list[str]]:
    checks = [
        ("主要用途/软件", r"办公|学习|设计|剪辑|游戏|编程|会议|绘图|建模|财务|网课|写作"),
        ("预算范围", r"预算|元|块|以内|不超过|左右|价位"),
        ("便携要求", r"出差|通勤|移动|轻薄|重量|携带"),
        ("系统与生态", r"鸿蒙|windows|苹果|手机|平板|生态|协同"),
        ("软件/外设兼容要求", r"软件|应用|打印机|投影|显示器|外设|兼容|驱动"),
    ]
    known = [label for label, pattern in checks if re.search(pattern, query, re.I)]
    missing = [label for label, _ in checks if label not in known]
    return known, missing


def _recommendations(query: str) -> list[dict[str, str]]:
    q = query.lower()
    if any(word in q for word in ("游戏", "电竞", "高刷")):
        names = ["MateBook GT 系列", "MateBook 14 酷睿 Ultra"]
        reason = "先核对具体游戏/专业软件、画质目标、外设及 Windows 版本要求，再安排实机测试。"
    elif any(word in q for word in ("大屏", "数字键盘", "财务", "表格")):
        names = ["MateBook D 16", "MateBook D 16 SE 版", "MateBook Fold 非凡大师"]
        reason = "优先验证大屏/数字键盘或多窗口任务是否更重要，并现场按任务体验。"
    elif any(word in q for word in ("鸿蒙", "手机", "平板", "协同", "华为设备")):
        names = ["HUAWEI MateBook 14（鸿蒙版）", "HUAWEI MateBook Pro S", "MateBook D 14"]
        reason = "先了解现有设备及实际协同任务；具体功能支持范围依机型、系统和版本而定，并用预算筛选配置。"
    elif any(word in q for word in ("轻", "便携", "通勤", "出差", "移动")):
        names = ["HUAWEI MateBook Pro S", "HUAWEI MateBook X系列", "MateBook D 14"]
        reason = "以重量、尺寸和移动使用体验作为候选比较项；请以具体配置实物和产品事实页为准。"
    elif any(word in q for word in ("预算", "便宜", "性价比", "学生", "入门")):
        names = ["MateBook D 14", "MateBook D 16 SE 版", "MateBook 14 酷睿 Ultra"]
        reason = "作为预算优先的候选方向；确认当前在售 SKU、系统、配置与实际价格后再比较。"
    else:
        names = ["HUAWEI MateBook 14（鸿蒙版）", "MateBook 14 酷睿 Ultra", "MateBook D 14"]
        reason = "先从系统路线、主要软件和预算三个维度缩小范围，目前不据此确定唯一机型。"
    return [{"name": name, "reason": reason} for name in names]


def analyze(query: str, kb: KnowledgeBase, channel: str = "门店沟通/私聊跟进") -> dict:
    query = query.strip()
    if not query:
        raise ValueError("请先输入客户原话或需求。")
    hits = kb.search(query, limit=7)
    known, missing = _profile(query)
    recommendations = _recommendations(query)
    source_map = []
    seen = set()
    for _, chunk in hits:
        if chunk.source not in seen:
            seen.add(chunk.source)
            source_map.append({"path": chunk.source, "title": chunk.title})
    excerpts = [
        {"title": chunk.title, "path": chunk.source, "text": chunk.text[:480]}
        for _, chunk in hits[:5]
    ]
    known_text = "、".join(known) if known else "尚未明确客户的主要用途和约束"
    missing_text = "、".join(missing[:4]) if missing else "暂无明显缺项，仍需确认具体销售配置"
    marketing = (
        f"建议渠道：{channel}。针对“{query[:80]}”，围绕客户实际任务说明产品选择理由；先讲需求，再用已核验的产品事实支撑，避免堆参数。\n\n"
        "内容草稿：‘先把每天要完成的任务说清楚，再挑真正用得上的电脑。我们可以按你的软件、预算和携带习惯，对照具体型号与配置现场体验；涉及价格、库存和活动，以核验当日的官方商品页/门店信息为准。欢迎带上常用软件清单到店体验。’"
    )
    return {
        "customer": {"summary": f"客户已提及：{known_text}。当前需求原话：{query}", "missing": missing_text},
        "recommendations": recommendations,
        "marketing": marketing,
        "demo": [
            "先复述客户的任务、预算与顾虑，请客户确认理解无误。",
            "挑 1–2 个候选 SKU，逐项核对系统、处理器、内存、存储和版本。",
            "用客户自己的软件/外设做 3–5 分钟任务演示；未测试的兼容性标记待测试。",
            "让客户亲自完成关键操作，并确认重量、屏幕、键盘等体验偏好。",
            "记录未确认项、责任人和回访时间，确认后再发送正式报价。",
        ],
        "quote": {
            "status": "未生成成交金额",
            "message": "当前版本不把知识库静态快照或内部价格政策当作实时报价。请在报价前核对完整 SKU、销售渠道、地区、当前商城结算页、库存、优惠/补贴条件、赠品与有效期；未核实字段留空并转人工复核。",
        },
        "next": [
            f"补问：{missing_text}。",
            "请客户提供常用软件/外设清单，并确认必须使用 Windows 还是可接受 HarmonyOS。",
            "核对当前在售 SKU 与门店可体验机，确认动态价格与权益后再发送报价。",
        ],
        "sources": source_map,
        "evidence": excerpts,
        "meta": {"indexed_files": kb.file_count, "indexed_chunks": len(kb.chunks), "mode": "本地检索 + 规则编排（无外部模型）"},
    }


def build_insight(payload: dict, kb: KnowledgeBase) -> dict:
    """Build a customer insight card from explicitly provided inputs only."""
    allowed_channels = {"门店沟通", "门店当面沟通", "微信私聊", "电话沟通", "视频会议", "小红书", "短视频/直播", "公众号/社群", "企业拜访"}

    def text(name: str, max_length: int = 500) -> str:
        value = payload.get(name, "")
        return str(value).strip()[:max_length] if value is not None else ""

    def choices(name: str, max_count: int = 12) -> list[str]:
        value = payload.get(name, [])
        if not isinstance(value, list):
            return []
        return [str(item).strip()[:80] for item in value[:max_count] if str(item).strip()]

    def selected_values(name: str, legacy_name: str, max_count: int = 12) -> list[str]:
        values = choices(name, max_count)
        legacy = text(legacy_name, 120)
        if not values and legacy:
            values = [legacy]
        return list(dict.fromkeys(values))

    def add_other(values: list[str], other_name: str) -> list[str]:
        other = text(other_name, 160)
        if other:
            values = [value for value in values if value != "其他"]
            values.append("其他：" + other)
        return list(dict.fromkeys(values))

    persona_values = add_other(selected_values("personas", "persona"), "persona_other")
    scene_values = add_other(selected_values("scenes", "scene"), "scene_other")
    needs = add_other(choices("needs"), "need_other")
    concern_values = add_other(selected_values("concerns", "concern"), "concern_other")
    trigger_values = add_other(selected_values("triggers", "trigger"), "trigger_other")
    channel_values = choices("channels", 12)
    legacy_channel = text("channel", 40)
    if not channel_values and legacy_channel:
        channel_values = [legacy_channel]
    channel_values = [value for value in dict.fromkeys(channel_values) if value in allowed_channels]
    if not channel_values:
        channel_values = ["门店沟通"]
    persona = "、".join(persona_values)
    scene = "、".join(scene_values)
    scene_detail = text("scene_detail")
    need_detail = text("need_detail")
    concern_detail = text("concern_detail")
    trigger = "、".join(trigger_values)
    customer_words = text("customer_words", 1200)
    priority_values = choices("priority_concerns", 12)
    legacy_priority = payload.get("priority_concern", "")
    if not priority_values:
        if isinstance(legacy_priority, list):
            priority_values = [str(item).strip()[:80] for item in legacy_priority if str(item).strip()]
        else:
            legacy_text = str(legacy_priority or "").strip()[:120]
            if legacy_text:
                priority_values = [legacy_text]
    if priority_values:
        priority_values = add_other(priority_values, "concern_other")
    if not priority_values:
        priority_values = concern_values[:]
    if not priority_values and concern_detail:
        priority_values = [concern_detail[:80]]
    priority_values = list(dict.fromkeys(priority_values))
    primary_concern = priority_values[0] if priority_values else ""
    priority_concern = "、".join(priority_values)
    channel = "、".join(channel_values)
    if not any((persona, scene, needs, concern_values, trigger, customer_words, scene_detail, need_detail, concern_detail)):
        raise ValueError("至少填写一项客户需求信息，再生成洞察卡。")

    def entry(value: str, empty: str = "尚未提供，建议继续询问") -> dict[str, str]:
        return {"value": value or empty, "status": "已记录" if value else "待追问", "basis": "顾客选择/填写" if value else "当前没有明确证据"}

    scene_value = "、".join(scene_values + ([scene_detail] if scene_detail else []))
    need_value = "、".join(needs + ([need_detail] if need_detail else []))
    concern_value = "、".join(concern_values + ([concern_detail] if concern_detail else []))
    raw_evidence = customer_words or "未记录自由表述；本卡仅使用上方已选择字段。"

    concern_key = primary_concern + " " + concern_detail
    if any(word in concern_key for word in ("预算", "价格", "费用", "促销")):
        strategy = "先确认预算上限、是否含配件与比较对象；复述顾客在意的价值，再核对当日具体 SKU 与授权渠道信息。不用静态价格催促成交。"
        opening = "“我先确认一下，您的预算是整机预算，还是也包含配件/软件？最希望优先满足哪两项？”"
    elif any(word in concern_key for word in ("软件", "兼容", "系统", "应用", "外设", "驱动")):
        strategy = "先问软件/外设的准确名称、版本和必须完成的任务；把兼容性作为门槛问题，安排官方资料核对或顾客自己的任务实测，未验证前不作肯定承诺。"
        named_concern = (concern_detail or primary_concern or "兼容性").strip()[:100]
        opening = f"“您提到的‘{named_concern}’，最关键的是哪款软件/外设和哪一步任务？我们按实际版本一起核对。”"
    elif any(word in concern_key for word in ("续航", "重量", "携带", "便携", "出差")):
        strategy = "把日常行程、连续使用时段和整套携带物问清；引导顾客现场体验具体配置。重量与续航只引用对应 SKU 的限定条件，不把主观感受说成规格。"
        opening = "“您通常会带电脑跑哪些场景？我们可以把充电器和常用外设也一起考虑，再按实际任务体验。”"
    elif any(word in concern_key for word in ("性能", "卡顿", "创作", "剪辑", "建模", "配置", "内存", "存储")):
        strategy = "把顾客的实际软件、项目规模和同时运行的任务问清；区分必须满足的性能门槛与偏好，优先以具体配置和真实工作样例验证。"
        opening = "“您最常做的那个项目大概是什么规模？我们先按这个任务确认配置需求，再看哪些体验是必须的。”"
    elif any(word in concern_key for word in ("屏幕", "键盘", "触控", "体验")):
        strategy = "确认顾客更在意的屏幕、输入或操作习惯，安排对应机型现场体验；亮度、色域、刷新率等参数须按具体 SKU 核对。"
        opening = "“屏幕和操作体验里，哪一点最影响您每天使用？我们可以先用实际机型对比感受。”"
    elif any(word in concern_key for word in ("品牌", "竞品", "比较")):
        strategy = "先确认比较对象、对应配置和使用任务，再按相同条件逐项对比；只陈述可核验差异，不贬低其他品牌，也不把主观偏好说成事实。"
        opening = "“您目前在比较哪些机型？我们可以把配置、任务体验和服务条件放在同一张清单里逐项核对。”"
    elif any(word in concern_key for word in ("库存", "活动", "到货", "权益")):
        strategy = "先记录所需型号、地区和时间要求，再核验当前库存、活动条件与有效期；动态信息以当日官方页面或门店确认结果为准，不用历史资料承诺。"
        opening = "“您希望什么时候拿到电脑、关注哪项活动？我先按具体型号和门店核对当前信息。”"
    elif any(word in concern_key for word in ("安全", "隐私", "售后", "保修", "维修", "服务", "数据")):
        strategy = "先澄清不可接受的风险和责任边界，再分别核对组织要求、官方服务规则或数据处理流程；未知政策转授权人员确认。"
        opening = "“您最希望提前确认的是哪一类风险？我先把适用条件和需要向官方/IT核验的部分分开记下来。”"
    elif primary_concern and primary_concern not in ("暂未表达", "还没有", "未明确"):
        strategy = "先请顾客用自己的话说明具体担心，再复述确认；补问比较对象、任务和不能接受的结果，再决定展示哪项事实或安排什么体验。"
        opening = "“我先确认一下，您最担心的是【顾客原话】带来的什么影响？我理解对了吗？”"
    else:
        strategy = "先围绕顾客的日常任务复述需求，请顾客确认；再追问最优先的两项和不能接受的情况。当前没有足够信息判断顾虑或购买动机，不预设心理。"
        opening = "“我先了解您一天里最常用电脑完成的三件事，再一起排一下优先级，可以吗？”"

    facts_query = " ".join(x for x in (persona, scene, scene_detail, " ".join(needs), need_detail, " ".join(concern_values), concern_detail, trigger, customer_words) if x)
    strategy_hits = kb.search("客户异议处理 确认 澄清 证据 取舍 下一步 用户原话", limit=24)
    scenario_hits = kb.search(facts_query + " 客户场景 访谈 问题清单 门槛 偏好 任务", limit=32) if facts_query else []

    def unique_sources(hits: list[tuple[float, Chunk]], prefix: str, limit: int) -> list[dict[str, str]]:
        result = []
        seen = set()
        for _, chunk in hits:
            if not chunk.source.startswith(prefix) or chunk.source in seen:
                continue
            seen.add(chunk.source)
            result.append({"title": chunk.title, "path": chunk.source, "excerpt": chunk.text[:360]})
            if len(result) >= limit:
                break
        return result

    evidence = unique_sources(strategy_hits, "P2-卖点话术库/", 1)
    scenario_sources = unique_sources(scenario_hits, "P8-客户场景库/", 12)
    scenario_hints = {
        "学习与网课": ("02-教育", "08-高校学生", "10-中小学生家庭"),
        "差旅/移动办公": ("06-移动办公",),
        "日常办公": ("06-移动办公",),
        "远程/居家办公": ("06-移动办公",),
        "内容创作": ("14-视频制作", "15-媒体编辑"),
        "编程/开发": ("12-软件开发",),
        "设计/制图/建模": ("13-设计创意", "20-建筑工程"),
        "财务/审计/文档": ("18-财税审计",),
        "会议/投屏/演示": ("06-移动办公",),
        "家庭共享": ("08-家庭换新", "10-中小学生家庭"),
        "企业部署": ("01-政企",),
    }
    persona_hints = {
        "学生": ("02-教育", "08-高校学生", "10-中小学生家庭"),
        "家长/家庭采购者": ("10-中小学生家庭", "08-家庭换新"),
        "中小学教师": ("09-中小学教师",),
        "高校/科研人员": ("07-高校教师", "11-科研机构"),
        "企业负责人/管理者": ("01-政企",),
        "企业采购/IT": ("01-政企",),
        "自由职业者": ("29-自由职业",),
        "内容创作者": ("14-视频制作", "15-媒体编辑"),
        "设计/工程专业人士": ("13-设计创意", "20-建筑工程"),
    }
    hints = list(dict.fromkeys(
        hint
        for values, mapping in ((scene_values, scenario_hints), (persona_values, persona_hints))
        for value in values
        for hint in mapping.get(value, ())
    ))
    matched_scenarios = [item for item in scenario_sources if any(hint in item["path"] for hint in hints)]
    evidence.extend(matched_scenarios[:2])
    if not any(item["path"].startswith("P2-") for item in evidence):
        p2_chunk = next((chunk for chunk in kb.chunks if chunk.source == "P2-卖点话术库/08-方法论/04-异议处理结构.md"), None)
        if p2_chunk:
            evidence.insert(0, {"title": p2_chunk.title, "path": p2_chunk.source, "excerpt": p2_chunk.text[:360]})
    return {
        "customer": {
            "persona": entry(persona),
            "scene": entry(scene_value),
            "needs": entry(need_value),
            "concern": entry(concern_value),
            "priority_concern": priority_concern,
            "priority_concerns": priority_values,
            "trigger": entry(trigger),
            "channel": channel,
        },
        "communication": {"strategy": strategy, "opening": opening},
        "raw_evidence": raw_evidence,
        "evidence": evidence,
        "follow_up": [
            f"补问身份/使用角色：{persona or '尚未记录'}。" if not persona else "请顾客确认已记录的身份/角色是否准确。",
            f"补问具体任务与使用环境：{scene_value or '尚未记录'}。" if not scene_value else "确认该场景中最重要、最不能中断的具体任务。",
            f"补问最在意的顾虑和购买时机：{concern_value or '顾客尚未表达'}；{trigger or '触发点尚未记录'}。" if not concern_values or not trigger_values else "复述顾虑和购买触发点，请顾客确认理解无误。",
        ],
        "meta": {"mode": "结构化顾客输入 + 本地知识库方法依据", "indexed_files": kb.file_count, "indexed_chunks": len(kb.chunks)},
    }


def default_kb_path() -> Path:
    return Path(os.environ.get("HUAWEI_PC_KB", str(DEFAULT_KB))).expanduser()
