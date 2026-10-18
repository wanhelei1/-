"""Evidence-grounded marketing content drafts for the Huawei PC MVP.

Standalone, standard-library-only module. It uses P2 audience cards, P6 platform
briefs and the P6 image index; it never invents testimonials, dynamic offers,
prices, inventory, performance claims, or image rights.

Example:
    from marketing_content_module import generate_marketing_content
    result = generate_marketing_content(
        "HUAWEI MateBook 14", platform="小红书", audience="学生用户"
    )
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_KB = (
    Path(__file__).resolve().parent
    / "knowledge-base"
    / "华为PC全板块深度知识库_v7"
)
PLATFORM_FILES = {
    "小红书": "小红书.md",
    "朋友圈": "朋友圈.md",
    "抖音": "短视频口播.md",
    "视频号": "短视频口播.md",
    "短视频": "短视频口播.md",
    "微信公众号": "微信公众号.md",
    "公众号": "微信公众号.md",
    "知乎": "知乎回答.md",
    "新闻稿": "新闻稿.md",
    "直播": "直播讲解.md",
    "门店": "门店长图.md",
    "门店长图": "门店长图.md",
}
AUDIENCE_FILES = {
    "学生": "学生用户沟通卡.md",
    "教师": "教师用户沟通卡.md",
    "商务": "商务差旅用户沟通卡.md",
    "差旅": "商务差旅用户沟通卡.md",
    "创作者": "内容创作者沟通卡.md",
    "内容创作者": "内容创作者沟通卡.md",
    "换新": "旧机换新用户沟通卡.md",
    "旧机换新": "旧机换新用户沟通卡.md",
    "管理者": "管理者沟通卡.md",
    "门店顾客": "门店顾客沟通卡.md",
}
FORBIDDEN_CLAIMS = (
    "全网最低", "闭眼入", "天花板", "性能提升", "续航一整天", "销量第一",
    "所有软件都能用", "全系标配", "库存紧张", "最后一天",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _find_model_dir(root: Path, product: str, section: str) -> Optional[Path]:
    parent = root / section
    if not parent.exists():
        return None
    query = product.strip().casefold()
    dirs = [p for p in parent.rglob("*") if p.is_dir()]
    exact = [p for p in dirs if p.name.casefold() == query]
    if exact:
        return exact[0]
    candidates = [p for p in dirs if p.name.casefold() in query or query in p.name.casefold()]
    return max(candidates, key=lambda p: len(p.name)) if candidates else None


def _section(text: str, heading: str) -> str:
    match = re.search(rf"(?m)^##\s+{re.escape(heading)}\s*$", text)
    if not match:
        return ""
    tail = text[match.end():]
    next_heading = re.search(r"(?m)^##\s+", tail)
    return tail[: next_heading.start()] if next_heading else tail


def _bullets(text: str) -> List[str]:
    return [re.sub(r"^\s*[-*]\s+", "", line).strip()
            for line in text.splitlines()
            if re.match(r"^\s*[-*]\s+", line) and len(line.strip()) > 3]


def _choose_audience_file(root: Path, product: str, audience: str) -> Optional[Path]:
    model_dir = _find_model_dir(root, product, "P2-卖点话术库/07-按型号角色")
    if model_dir is None:
        return None
    key = next((k for k in AUDIENCE_FILES if k in audience), None)
    filename = AUDIENCE_FILES.get(key) if key else "门店顾客沟通卡.md"
    path = model_dir / filename
    return path if path.exists() else None


def _product_facts(card: str) -> List[str]:
    section = _section(card, "本型号可用事实锚点")
    if not section:
        section = _section(card, "事实锚点")
    return _bullets(section)


def _audience_prompt(card: str) -> str:
    if not card:
        return ""
    lines = card.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^#{1,3}\s+.*(?:先核|关键问题|需求确认)", line):
            for candidate in lines[index + 1:index + 8]:
                text = re.sub(r"^\s*(?:[-*]|\d+\.)\s*", "", candidate).strip()
                if text and not text.startswith("#"):
                    return text
    return ""


def _pick_fact(facts: List[str], audience_text: str, goal: str) -> str:
    terms = {
        "学习": ("屏", "触控", "内存", "接口", "学习", "重量", "软件"),
        "创作": ("屏", "色", "内存", "存储", "接口", "创作"),
        "商务": ("会议", "摄像头", "麦克风", "接口", "重量", "协同"),
        "通勤": ("重量", "厚度", "电池", "接口"),
        "办公": ("屏", "接口", "协同", "摄像头", "多任务"),
    }
    focus = next((vals for key, vals in terms.items() if key in audience_text + goal), terms["办公"])
    return next((fact for word in focus for fact in facts if word in fact), facts[0] if facts else "")


def _image_suggestions(root: Path, product: str, limit: int = 3) -> List[Dict[str, str]]:
    model_dir = _find_model_dir(root, product, "P1-产品参数库")
    if model_dir:
        exact_index = model_dir / "图片索引.csv"
        if exact_index.exists():
            matches = []
            with exact_index.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    matches.append({
                        "name": row.get("文件名", ""),
                        "description": row.get("官网图片说明", ""),
                        "image_url": row.get("原始图片URL", ""),
                        "page_url": row.get("来源页面", ""),
                        "usage_note": row.get("建议用途", "按画面含义使用，发布前核对版本与授权"),
                        "rights_status": "官方索引素材；发布前仍须核验品牌规范及授权范围",
                    })
                    if len(matches) >= limit:
                        break
            if matches:
                return matches
    path = root / "P6-营销素材库" / "04-图片" / "02-华为商城电脑专区素材" / "图片索引.csv"
    if not path.exists():
        return []
    tokens = [t.casefold() for t in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}", product)
              if len(t) > 1 and t.casefold() not in {"huawei", "华为"}]
    matches = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            label = " ".join((row.get("文件名", ""), row.get("画面说明", ""))).casefold()
            if tokens and all(token in label for token in tokens):
                matches.append({
                    "name": row.get("文件名", ""),
                    "description": row.get("画面说明", ""),
                    "image_url": row.get("原始图片URL", ""),
                    "page_url": row.get("页面来源", ""),
                    "captured_at": row.get("抓取日期", ""),
                    "usage_note": row.get("使用提示", "发布前核对型号与素材授权"),
                    "rights_status": "需发布前核验授权与适用型号",
                })
            if len(matches) >= limit:
                break
    return matches


def _strategy(platform: str, audience: str, goal: str) -> str:
    base = {
        "小红书": "用选购清单/版本避坑切入；封面提出具体问题，正文按场景、事实、取舍展开，结尾提问促评论。",
        "朋友圈": "采用顾问式单场景分享；每条只讲一个理由，邀请私聊或带设备到店验证，避免群发促销口吻。",
        "抖音": "一个动作证明一个购买理由；用问题钩子、型号身份、现场演示、适用边界和保存/到店 CTA 组织短视频。",
        "视频号": "用完整解释建立可信度；按事实、演示、适用条件展开，给家人/同事共同决策者留出理解时间。",
        "微信公众号": "围绕一个真实选购问题做结构化解释；先讲场景，再列可核验事实、版本差异和行动清单。",
        "知乎": "先回答具体问题，再给适用条件、验证方法与不适用场景；避免把体验推断写成普遍结论。",
        "新闻稿": "以可核验发布信息为主，先确认官方公告、日期和发布主体；没有公告证据时仅生成待核实草稿。",
        "直播": "按提问、实物演示、版本提醒、互动答疑推进；演示失败时不以剪辑或口播掩盖。",
        "门店": "制作问题—事实—现场验证—咨询入口的导购长图，参数旁标清版本与条件。",
    }
    platform_key = "视频号" if platform == "视频号" else "抖音" if platform in ("短视频", "抖音") else "门店" if platform in ("门店", "门店长图") else "微信公众号" if platform == "公众号" else platform
    return f"{base.get(platform_key, '以单一用户任务为主线，说明可核验事实、适用边界和下一步验证动作。')} 内容目标：{goal or '引导有效咨询'}；目标人群：{audience or '待指定'}。"


def generate_marketing_content(
    product: str,
    platform: str = "小红书",
    audience: str = "门店顾客",
    goal: str = "引导咨询",
    scenario: str = "",
    knowledge_base_dir: Optional[str | Path] = None,
) -> Dict[str, object]:
    """Create a structured, traceable marketing draft from local P2/P6 materials.

    Returns platform, strategy, title, body, CTA, image suggestions, sources,
    compliance checks and missing-evidence warnings. Output is a draft for review.
    """
    root = Path(knowledge_base_dir) if knowledge_base_dir else DEFAULT_KB
    platform_file = PLATFORM_FILES.get(platform)
    if platform_file is None:
        raise ValueError(f"unsupported platform {platform!r}; choose from {', '.join(PLATFORM_FILES)}")
    p6_dir = _find_model_dir(root, product, "P6-营销素材库/09-按型号平台")
    p6_path = p6_dir / platform_file if p6_dir else None
    p2_path = _choose_audience_file(root, product, audience)
    warnings: List[str] = []
    p6_text = _read(p6_path) if p6_path and p6_path.exists() else ""
    p2_text = _read(p2_path) if p2_path else ""
    facts = _product_facts(p6_text)
    if not p6_text:
        warnings.append("未找到该产品的平台任务卡；当前仅能生成通用框架，不补写产品参数。")
    if not facts:
        warnings.append("任务卡未提取到明确事实锚点；正文不生成具体参数，发布前需回到P1核验。")
    if not p2_text:
        warnings.append("未找到匹配的P2受众沟通卡；受众痛点按通用提问处理。")
    chosen_fact = _pick_fact(facts, audience, goal)
    audience_prompt = _audience_prompt(p2_text)
    product_name = p6_dir.name if p6_dir else product.strip()
    angle = scenario.strip() or audience_prompt or ("先确认核心任务与版本，再看参数是否匹配" if not chosen_fact else chosen_fact.split("；")[0].rstrip("。"))
    title = f"{product_name}怎么选？先核对这件事"
    if "鸿蒙版" in product_name:
        title = f"{product_name}怎么选？先核对这件事"
    if platform == "小红书":
        body = (
            f"选电脑时，别先被一串参数带着走。先把自己的任务说清楚：{angle}。\n\n"
            f"关于{product_name}，当前资料可引用的事实是：{chosen_fact or '暂缺可核验事实'}。"
            "这条信息只对应资料所列版本；具体 SKU、系统和配置仍要逐项确认。\n\n"
            "如果你常用的软件、外设或课程工具有明确要求，先带上名称和版本做兼容核验；屏幕、接口等体验也建议按目标版本现场确认。"
            "不要只凭系列名推断适用性。\n\n"
            f"你最想先确认哪一项：版本、软件，还是接口？评论告诉我你的使用场景。\n\n"
            "不同销售版本配置可能不同，请以华为官方规格页及实际销售 SKU 为准。"
        )
        cta = "评论留下具体任务/软件版本，或预约到店带常用文件和外设核验。"
    elif platform == "朋友圈":
        body = (
            f"最近有人问{product_name}适不适合{audience}。我建议先别急着看一长串参数，先确认：{angle}。\n"
            f"目前可核验的一项产品事实：{chosen_fact or '具体配置待按 SKU 核实'}。不同版本可能有差异，软件兼容和当日价格也要按实际情况确认。"
            "有需要可以带常用文件、软件名称或外设来店里逐项核对。"
        )
        cta = "私信告知具体任务与软件/外设型号，预约一次针对性核验。"
    elif platform in ("抖音", "视频号", "短视频"):
        body = (
            f"开场（问题钩子）：选{product_name}，你最该先确认的是什么？\n"
            f"镜头一（型号身份）：展示产品与完整型号。\n镜头二（事实）：{chosen_fact or '展示规格页并核对具体配置'}\n"
            "镜头三（现场验证）：用目标软件/文件或外设做真实操作；没有完成验证的功能不作保证。\n"
            "收束：不同销售版本可能不同，先按 SKU 核实，再判断是否适合你的任务。"
        )
        cta = "收藏核对清单；评论具体软件/外设型号，或预约到店实测。"
    else:
        body = (
            f"围绕“{angle}”，本文先给出核验路径，再说明{product_name}的适用边界。\n\n"
            f"已从对应平台任务卡提取的事实锚点：{chosen_fact or '暂无可引用事实，需回到P1与官方页面核验'}。"
            "任何配置、功能或兼容结论均应对应完整销售 SKU 与官方来源；动态价格、活动、库存和服务权益应在发布/报价时重新核验。\n\n"
            "建议读者准备真实软件版本、文件或外设清单，到店或通过官方规格/支持页面逐项验证。"
        )
        cta = "留言提供具体使用任务与版本信息，获取逐项核验建议。"
    if not facts:
        body = f"{product_name}的具体参数与适用版本目前缺少可引用证据。建议先确认完整 SKU、系统版本和使用任务，再对照华为官方规格页核验。\n\n{cta}"
    images = _image_suggestions(root, product_name)
    if not images:
        warnings.append("图片索引未找到可确认对应本型号的素材；优先检索P1型号图片索引或官方素材页，不用通用图冒充实拍。")
    # Include the image selection guide and P2 fact-boundary policy as review sources.
    guide = root / "P6-营销素材库" / "04-图片" / "图片选用与命名指南.md"
    fact_policy = root / "P2-卖点话术库" / "00-使用说明" / "话术事实边界.md"
    p5_policy = root / "P5-培训赋能库" / "09-系统课程" / "32-图片来源与图注" / "讲义.md"
    sources = [str(p) for p in (p6_path, p2_path, guide, fact_policy, p5_policy) if p and p.exists()]
    found_claims = [claim for claim in FORBIDDEN_CLAIMS if claim in title + "\n" + body]
    return {
        "product": product_name,
        "platform": platform,
        "content_strategy": _strategy(platform, audience, goal),
        "title": title,
        "body": body,
        "call_to_action": cta,
        "recommended_images": images,
        "image_source_note": "推荐素材仅供选型；发布前须核对原始来源、适用型号、权利状态及品牌规范。" if images else "暂无型号匹配的已索引图片；未推荐无来源图片。",
        "evidence_facts": facts,
        "audience_validation_prompt": audience_prompt,
        "sources": sources,
        "warnings": warnings,
        "compliance": {
            "draft_requires_human_review": True,
            "forbidden_claims_detected": found_claims,
            "dynamic_price_or_inventory_included": False,
            "testimonial_or_first_person_experience_invented": False,
        },
    }


def format_marketing_markdown(result: Dict[str, object]) -> str:
    """Render a generated result as a readable Markdown deliverable."""
    lines = [
        f"## {result['product']}｜{result['platform']}",
        f"**内容策略：** {result['content_strategy']}",
        f"**标题：** {result['title']}",
        "**正文：**", str(result["body"]),
        f"**行动引导：** {result['call_to_action']}",
        "**推荐图片与来源：**",
    ]
    images = result.get("recommended_images", [])
    if images:
        lines.extend(f"- {i['name']}｜{i['description']}｜[图片]({i['image_url']})｜来源：[页面]({i['page_url']})｜{i['rights_status']}" for i in images)
    else:
        lines.append("- 无可确认的型号匹配图片；请从型号图片索引或官方素材页检索并核验授权。")
    lines.append("**依据：**")
    lines.extend(f"- {source}" for source in result.get("sources", []))
    if result.get("warnings"):
        lines.append("**待核验：**")
        lines.extend(f"- {item}" for item in result["warnings"])
    return "\n\n".join(lines)


if __name__ == "__main__":
    print(format_marketing_markdown(generate_marketing_content("HUAWEI MateBook 14", "小红书", "学生用户")))
