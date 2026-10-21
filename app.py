"""No-key, evidence-grounded store growth assistant MVP server.

Run with: python app.py [--host 0.0.0.0] [--port 7860]
Uses only the Python standard library and the adjacent knowledge-base folder.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from modules.follow_up.follow_up_module import create_plan as create_follow_up_plan
from modules.follow_up.follow_up_module import update_plan_status, update_task as update_follow_up_task
from modules.demo_script.demo_script_module import generate_demo_script
from modules.marketing.marketing_content_module import generate_marketing_content
from modules.pricing.pricing_module import build_quote_status, load_price_records
from modules.recommendation.retrieval_adapter import (
    RetrievalAdapterError,
    mode_label,
    retrieve_with_adapter,
)
from modules.workflow.store_growth_workflow import (
    run_customer_insight,
    run_customer_recommendation,
    run_store_growth_workflow,
)

BASE = Path(__file__).resolve().parent
KB = BASE / "knowledge-base" / "华为PC全板块深度知识库_v7"
P1 = KB / "P1-产品参数库"
PRICE_SNAPSHOTS = P1 / "08-官方公开价格快照" / "官方价格快照.csv"
SCENARIOS = {
    "门店零售": "P8-客户场景库/04-门店/门店场景问题.md",
    "内容创作": "P8-客户场景库/05-内容创作/内容创作场景卡.md",
    "移动办公": "P8-客户场景库/06-移动办公/移动办公场景卡.md",
    "学生学习": "P8-客户场景库/07-学生学习/学生学习场景卡.md",
    "家庭换新": "P8-客户场景库/08-家庭换新/家庭换新场景卡.md",
    "商务管理": "P8-客户场景库/09-商务管理/商务管理场景卡.md",
}


def _catalog():
    items = []
    if not P1.exists():
        return items
    for facts_path in sorted(P1.rglob("产品事实.md")):
        model_dir = facts_path.parent
        if model_dir.name in {"00-全库横向索引", "07-扩展产品目录", "08-官方公开价格快照"}:
            continue
        items.append({"id": model_dir.name, "label": model_dir.name, "source": str(facts_path.relative_to(BASE))})
    return items


COMPARISON_MATRIX = P1 / "00-全库横向索引" / "全型号参数联合矩阵.csv"
COMPARISON_FIELDS = (
    ("操作系统", "操作系统"),
    ("屏幕规格", "屏幕"),
    ("处理器", "处理器"),
    ("内存", "内存"),
    ("存储", "存储"),
    ("尺寸重量", "尺寸与重量"),
    ("电池", "电池"),
    ("接口", "接口"),
    ("摄像头", "摄像头"),
    ("音频", "音频"),
    ("特色应用", "特色应用"),
)


def _comparison_category(name, source):
    """Classify only from the product name and local fact-file path."""
    text = f"{name} {source}".casefold()
    if any(marker in text for marker in ("手机", "phone", "pura", "nova", "pocket")):
        return "手机"
    if any(marker in text for marker in ("matebook", "笔记本", "电脑")):
        return "电脑"
    return "其他产品"


def _comparison_catalog():
    """Expose comparison-ready products backed by the local fact matrix only."""
    if not COMPARISON_MATRIX.exists():
        return []
    items = []
    with COMPARISON_MATRIX.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            product_id = (row.get("型号") or "").strip()
            source = (row.get("本地事实源") or "").strip()
            if not product_id or not source or not (KB / source).is_file():
                continue
            specifications = {
                field: (row.get(field) or "").strip()
                for field, _label in COMPARISON_FIELDS
            }
            if not any(specifications.values()):
                continue
            items.append(
                {
                    "id": product_id,
                    "label": product_id,
                    "category": _comparison_category(product_id, source),
                    "source": source,
                    "specifications": specifications,
                }
            )
    return sorted(items, key=lambda item: item["label"])


def _comparison_item_by_id(product_id):
    return next(
        (item for item in _comparison_catalog() if item["id"] == (product_id or "").strip()),
        None,
    )


def _compare_products(payload):
    left = _comparison_item_by_id(str(payload.get("left_product", "")))
    right = _comparison_item_by_id(str(payload.get("right_product", "")))
    if not left or not right:
        raise ValueError("请选择两款有本地规格来源的产品")
    if left["id"] == right["id"]:
        raise ValueError("请选择两款不同的产品型号")

    specifications = []
    difference_count = 0
    for field, label in COMPARISON_FIELDS:
        left_value = left["specifications"].get(field, "")
        right_value = right["specifications"].get(field, "")
        if not left_value or not right_value:
            status = "资料未提供"
        elif left_value == right_value:
            status = "相同"
        else:
            status = "不同"
            difference_count += 1
        specifications.append(
            {
                "field": field,
                "label": label,
                "left": left_value or "资料未提供",
                "right": right_value or "资料未提供",
                "status": status,
            }
        )
    return {
        "left": {key: left[key] for key in ("id", "label", "category", "source")},
        "right": {key: right[key] for key in ("id", "label", "category", "source")},
        "specifications": specifications,
        "difference_count": difference_count,
        "notice": "仅对比本地事实矩阵中已收录的规格；销售版本、可选配置与当前状态请以官方页面和实际销售版本为准。",
    }


def _snapshot_date(value):
    match = re.search(r"\d{4}-\d{2}-\d{2}", value or "")
    return match.group(0) if match else "待核验"


def _parse_variant_configuration(configuration):
    """Read only explicit memory, storage, color, and feature values from one SKU snapshot."""
    normalized = (configuration or "").replace("；", "/").replace("，", "/")
    parts = [part.strip() for part in normalized.split("/") if part.strip()]
    memory = next((part for part in parts if re.fullmatch(r"\d+GB", part, re.I)), "")
    memory_index = parts.index(memory) if memory in parts else -1
    storage = next(
        (part for part in parts[memory_index + 1 :] if re.fullmatch(r"(?:\d+GB|\d+TB)", part, re.I)),
        "",
    )
    colors = ("原野绿", "樱粉金", "深空灰", "烟云灰", "仲夏紫", "晨曦黄", "天际白", "流光金", "幻影黑", "晴蓝")
    color = next((part for part in parts if part in colors), "")
    processor = next((part for part in parts if re.fullmatch(r"麒麟[\w\s+]+", part)), "")
    extras = [part for part in parts if part not in {memory, storage, color, "HarmonyOS", processor}]
    return {"memory": memory, "storage": storage, "color": color, "processor": processor, "extras": extras}


def _product_name_key(value):
    return re.sub(r"[（）()\s]", "", value or "").replace("鸿蒙版", "").casefold()


def _image_path_matches_product(path, product_name):
    key = _product_name_key(product_name)
    return key in {_product_name_key(part) for part in path.parts}


def _official_color_images(product_name, color, sku):
    """Return images only when their Vmall URL names the exact color SKU."""
    sku_terms = re.findall(r"(?:prdId|sbomCode)=[^;&\s]+", sku or "")
    if not color or {term.split("=", 1)[0] for term in sku_terms} != {"prdId", "sbomCode"}:
        return []
    matches = []
    for path in P1.rglob("图片索引.csv"):
        if "商城款式图片" not in path.parts or not _image_path_matches_product(path, product_name):
            continue
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    description = row.get("官网图片说明") or row.get("画面说明") or ""
                    source_url = row.get("商品页URL") or row.get("来源页面") or ""
                    indexed_product = row.get("产品型号", "")
                    if color not in description or not row.get("原始图片URL"):
                        continue
                    if not all(term in source_url for term in sku_terms):
                        continue
                    if indexed_product and _product_name_key(indexed_product) != _product_name_key(product_name):
                        continue
                    matches.append(
                        {
                            "url": row["原始图片URL"],
                            "description": description,
                            "source_url": source_url,
                            "captured_at": row.get("抓取日期") or "本地官方图片索引",
                        }
                    )
        except (OSError, UnicodeError, csv.Error):
            continue
    seen = set()
    return [item for item in matches if not (item["url"] in seen or seen.add(item["url"]))]


def _variant_catalog():
    """Expose exact, locally verified Huawei price snapshots without inventing combinations."""
    if not PRICE_SNAPSHOTS.exists():
        return []
    variants = []
    with PRICE_SNAPSHOTS.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            price_text = (row.get("页面金额（元）") or "").strip()
            verification = (row.get("核验状态") or "").strip()
            price_type = (row.get("价格类型") or "").strip()
            configuration = (row.get("精确款式") or "").strip()
            product_name = (row.get("规范产品名称") or "").strip()
            source_url = (row.get("官方URL") or "").strip()
            sku = (row.get("型号或SKU") or "").strip()
            if not (price_text and "已核验" in verification and source_url and sku):
                continue
            if not price_type.startswith(("官方商城页面价", "当前商城页面价")):
                continue
            if any(word in configuration for word in ("专区默认", "官网产品页", "下架", "未展开", "颜色未展开", "版本与颜色未展开")):
                continue
            parsed = _parse_variant_configuration(configuration)
            if not all((parsed["memory"], parsed["storage"], parsed["color"])):
                continue
            try:
                price = float(re.sub(r"[^0-9.]", "", price_text))
            except ValueError:
                continue
            image_product = product_name
            images = _official_color_images(image_product, parsed["color"], sku)
            variants.append(
                {
                    "id": (row.get("记录ID") or "").strip(),
                    "product": product_name,
                    "configuration": configuration,
                    "memory": parsed["memory"],
                    "storage": parsed["storage"],
                    "color": parsed["color"],
                    "processor": parsed["processor"],
                    "features": parsed["extras"],
                    "sku": sku,
                    "price": price,
                    "price_type": price_type,
                    "verified_at": _snapshot_date(row.get("核验时间", "")),
                    "source_title": (row.get("来源标题") or "").strip(),
                    "source_url": source_url,
                    "evidence": (row.get("证据摘要") or "").strip(),
                    "images": images,
                }
            )
    # Some sources duplicate the same fully specified configuration. Only merge
    # records when every customer-visible configuration field matches; otherwise
    # a distinct SKU remains a distinct UI option.
    unique = {}
    for item in variants:
        key = (
            item["product"], item["memory"], item["storage"], item["color"],
            item["processor"], tuple(sorted(item["features"])), item["price"],
        )
        previous = unique.get(key)
        strength = (item["verified_at"], "动态页" in item["evidence"], "sbomCode=" in item["sku"])
        old_strength = (previous["verified_at"], "动态页" in previous["evidence"], "sbomCode=" in previous["sku"]) if previous else None
        if previous is None or strength > old_strength:
            unique[key] = item
    return sorted(unique.values(), key=lambda item: (item["product"], item["price"], item["id"]))


def _variant_by_id(variant_id):
    return next((item for item in _variant_catalog() if item["id"] == (variant_id or "").strip()), None)


def _quote_for_payload(payload):
    variant = _variant_by_id(str(payload.get("variant_id", "")))
    if not variant:
        return build_quote_status(str(payload.get("product", ""))).to_dict()
    record = next((item for item in load_price_records() if item.record_id == variant["id"]), None)
    if record is None:
        return build_quote_status(f"{variant['product']} {variant['configuration']}").to_dict()
    return build_quote_status(
        f"{record.product_name} {record.configuration}", records=[record]
    ).to_dict()


def _scenario_questions(name):
    path = KB / SCENARIOS.get(name, SCENARIOS["门店零售"])
    if not path.exists():
        return ["客户要完成的首要任务是什么？", "有哪些必须使用的软件和版本？", "哪些外设或组织规则必须通过现场测试？"]
    text = path.read_text(encoding="utf-8-sig")
    questions = []
    for line in text.splitlines():
        match = re.match(r"^\s*(?:\d+[.、]|[-*])\s*(.{8,180}[？?])\s*$", line)
        if match and len(questions) < 8:
            questions.append(match.group(1).strip())
    return questions or ["客户要完成的首要任务是什么？", "有哪些必须使用的软件和版本？", "哪些外设或组织规则必须通过现场测试？"]


def _resolve_product(name):
    if not name:
        return None
    choices = _catalog()
    query = name.casefold().strip()
    exact = next((p for p in choices if p["id"].casefold() == query), None)
    if exact:
        return exact
    matches = [p for p in choices if query in p["id"].casefold() or p["id"].casefold() in query]
    return max(matches, key=lambda p: len(p["id"])) if matches else None


def _product_evidence(product):
    if not product:
        return {"summary": "尚未选择明确产品型号。", "facts": [], "source": ""}
    path = BASE / product["source"]
    text = path.read_text(encoding="utf-8-sig")
    lines = [line.strip(" -*\t") for line in text.splitlines() if line.strip()]
    facts = [line for line in lines if any(k in line for k in ("HarmonyOS", "Windows", "英寸", "kg", "GB", "OLED", "Wi-Fi", "触控", "接口"))]
    return {"summary": "仅列出产品官方事实文件中的规格摘录；具体配置需按完整 SKU 核对。", "facts": facts[:8], "source": product["source"]}


def _consult(payload):
    selected_variant = _variant_by_id(str(payload.get("variant_id", "")))
    product_query = str(payload.get("product", "")) or (selected_variant["product"] if selected_variant else "")
    product = _resolve_product(product_query)
    scenario = str(payload.get("scenario", "门店零售"))
    customer_task = str(payload.get("customer_task", "")).strip()[:1200]
    required_software = str(payload.get("required_software", "")).strip()[:500]
    peripherals = str(payload.get("peripherals", "")).strip()[:500]
    gate_conditions = [x for x in [required_software, peripherals] if x]
    quote = _quote_for_payload(payload) if (product_query or selected_variant) else None
    return {
        "selected_product": product,
        "selected_variant": selected_variant,
        "scenario": scenario,
        "customer_task": customer_task,
        "scenario_questions": _scenario_questions(scenario),
        "requirements": [
            {"label": "核心任务", "value": customer_task or "待访谈确认", "status": "待补充" if not customer_task else "客户陈述"},
            {"label": "指定软件与版本", "value": required_software or "未提供，不据此判断兼容", "status": "待验证" if required_software else "待确认"},
            {"label": "外设与连接方式", "value": peripherals or "未提供，不据此判断兼容", "status": "待验证" if peripherals else "待确认"},
        ],
        "decision": "先补齐门槛证据，再安排目标环境试测；当前不输出无证据的唯一推荐。" if gate_conditions else "请先记录客户真实任务、软件版本和外设型号，未知项保持待确认。",
        "product_evidence": _product_evidence(product),
        "quote": quote,
        "next_steps": ["记录完整销售 SKU、系统版本和地区。", "由客户或软件/外设厂商确认兼容要求；在目标门店环境完成脱敏实测。", "保存来源、核验日期、测试结果和限制；动态价格及权益发布前重新核验。"],
        "sources": [SCENARIOS.get(scenario, SCENARIOS["门店零售"]), product["source"] if product else ""],
    }


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _knowledge_query(payload):
    query = str(payload.get("query", "")).strip()[:1000]
    if not query:
        raise ValueError("请输入知识库问题")
    response = retrieve_with_adapter(query, top_k=payload.get("top_k", 5))
    return {
        "mode": response.mode,
        "mode_label": mode_label(response.mode),
        "warnings": response.warnings,
        "results": [
            {
                "text": item.text,
                "source": item.source,
                "url": item.url,
                "page": item.page,
                "section": item.section,
                "local_path": item.local_path,
                "line_start": item.line_start,
                "line_end": item.line_end,
                "score": item.score,
                "demo": item.demo,
            }
            for item in response.results
        ],
    }


def _follow_up_task_update(payload):
    plan = payload.get("plan")
    changes = payload.get("changes", {})
    if not isinstance(plan, dict) or not isinstance(changes, dict):
        raise ValueError("plan 和 changes 必须是对象")
    allowed = {"status", "date", "channel", "message", "note"}
    if set(changes) - allowed:
        raise ValueError("changes 包含不支持的字段")
    return update_follow_up_task(
        plan,
        payload.get("task_number"),
        status=changes.get("status"),
        date_value=changes.get("date"),
        channel=changes.get("channel"),
        message=changes.get("message"),
        note=changes.get("note"),
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "StoreGrowthMVP/1.0"

    def _respond(self, status, body, content_type="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            target = BASE / "index.html"
            if not target.exists():
                return self._respond(503, "index.html is not installed", "text/plain; charset=utf-8")
            return self._respond(200, target.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/bootstrap":
            return self._respond(200, _json_bytes({"products": _catalog(), "comparison_products": _comparison_catalog(), "variants": _variant_catalog(), "scenarios": list(SCENARIOS), "platforms": ["小红书", "朋友圈", "抖音", "视频号", "微信公众号", "知乎", "新闻稿", "直播", "门店长图"], "api_key_required": False, "knowledge_base_available": KB.exists()}))
        if path == "/health":
            return self._respond(200, _json_bytes({"ok": True, "knowledge_base_available": KB.exists(), "products": len(_catalog())}))
        self._respond(404, _json_bytes({"error": "not_found"}))

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 64_000:
                return self._respond(413, _json_bytes({"error": "request_too_large"}))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                return self._respond(400, _json_bytes({"error": "JSON object required"}))
            if path == "/api/workflow":
                result = run_store_growth_workflow(payload)
            elif path == "/api/recommendation":
                result = run_customer_recommendation(payload)
            elif path == "/api/knowledge-query":
                try:
                    result = _knowledge_query(payload)
                except RetrievalAdapterError as exc:
                    return self._respond(503, _json_bytes({"error": "retrieval_unavailable", "detail": str(exc)}))
            elif path == "/api/followups/plan":
                result = create_follow_up_plan(
                    start_date=payload.get("start_date"),
                    label=payload.get("label"),
                    channel=payload.get("channel", "微信"),
                    sequence=payload.get("sequence", 1),
                )
            elif path == "/api/followups/task":
                result = _follow_up_task_update(payload)
            elif path == "/api/followups/status":
                plan = payload.get("plan")
                if not isinstance(plan, dict):
                    raise ValueError("plan 必须是对象")
                result = update_plan_status(plan, payload.get("status"))
            elif path == "/api/insight":
                result = run_customer_insight(payload)
            elif path == "/api/consult":
                result = _consult(payload)
            elif path == "/api/quote":
                result = _quote_for_payload(payload)
            elif path == "/api/product-compare":
                result = _compare_products(payload)
            elif path == "/api/demo-script":
                result = generate_demo_script(payload, knowledge_base_dir=KB)
            elif path == "/api/marketing":
                result = generate_marketing_content(
                    str(payload.get("product", "")), str(payload.get("platform", "小红书")),
                    str(payload.get("audience", "门店顾客")), str(payload.get("goal", "引导咨询")),
                    str(payload.get("scenario", "")), knowledge_base_dir=KB,
                )
            else:
                return self._respond(404, _json_bytes({"error": "not_found"}))
            self._respond(200, _json_bytes(result))
        except json.JSONDecodeError:
            self._respond(400, _json_bytes({"error": "invalid_json"}))
        except ValueError as exc:
            self._respond(400, _json_bytes({"error": str(exc)}))
        except OSError as exc:
            self._respond(500, _json_bytes({"error": "request_failed", "detail": str(exc)}))

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))


def main():
    parser = argparse.ArgumentParser(description="No-key evidence-grounded store growth MVP")
    parser.add_argument("--host", default="127.0.0.1", help="Use 0.0.0.0 for hosted environments")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Store Growth MVP listening at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
