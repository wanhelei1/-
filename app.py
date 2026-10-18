"""No-key, evidence-grounded store growth assistant MVP server.

Run with: python app.py [--host 0.0.0.0] [--port 7860]
Uses only the Python standard library and the adjacent knowledge-base folder.
"""
from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from modules.follow_up.follow_up_module import create_plan as create_follow_up_plan
from modules.follow_up.follow_up_module import update_plan_status, update_task as update_follow_up_task
from modules.marketing.marketing_content_module import generate_marketing_content
from modules.pricing.pricing_module import build_quote_status
from modules.recommendation.retrieval_adapter import (
    RetrievalAdapterError,
    mode_label,
    retrieve_with_adapter,
)
from modules.workflow.store_growth_workflow import run_customer_insight, run_store_growth_workflow

BASE = Path(__file__).resolve().parent
KB = BASE / "knowledge-base" / "华为PC全板块深度知识库_v7"
P1 = KB / "P1-产品参数库"
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
    product = _resolve_product(str(payload.get("product", "")))
    scenario = str(payload.get("scenario", "门店零售"))
    customer_task = str(payload.get("customer_task", "")).strip()[:1200]
    required_software = str(payload.get("required_software", "")).strip()[:500]
    peripherals = str(payload.get("peripherals", "")).strip()[:500]
    gate_conditions = [x for x in [required_software, peripherals] if x]
    quote = build_quote_status(product["id"] if product else str(payload.get("product", ""))).to_dict() if payload.get("product") else None
    return {
        "selected_product": product,
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
            return self._respond(200, _json_bytes({"products": _catalog(), "scenarios": list(SCENARIOS), "platforms": ["小红书", "朋友圈", "抖音", "视频号", "微信公众号", "知乎", "新闻稿", "直播", "门店长图"], "api_key_required": False, "knowledge_base_available": KB.exists()}))
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
                result = build_quote_status(str(payload.get("product", ""))).to_dict()
            elif path == "/api/marketing":
                result = generate_marketing_content(
                    str(payload.get("product", "")), str(payload.get("platform", "小红书")),
                    str(payload.get("audience", "门店顾客")), str(payload.get("goal", "引导咨询")),
                    str(payload.get("scenario", "")), knowledge_base_dir=KB,
                )
            else:
                return self._respond(404, _json_bytes({"error": "not_found"}))
            self._respond(200, _json_bytes(result))
        except ValueError as exc:
            self._respond(400, _json_bytes({"error": str(exc)}))
        except (OSError, json.JSONDecodeError) as exc:
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
