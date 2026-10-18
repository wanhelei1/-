"""Shared, offline follow-up plan rules for the web UI and CLI."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

STAGES = [
    ("今天", 0, "回顾当日沟通，确认需求、重点顾虑和约定的下一步。", "您好，感谢今天沟通。为避免遗漏，我把您关注的【使用场景】和【重点问题】整理如下：【待确认事项】。如果有理解不准确的地方，您方便时告诉我，我再核对。"),
    ("第1天", 1, "补充顾客明确提出需要的资料，确认遗留问题是否解决。", "您好，昨天沟通后，我把您关心的【问题】和相关资料整理好了。涉及配置、软件兼容或当前权益的内容，我会按完整型号和官方信息核对。您还希望我补充哪一点？"),
    ("第3天", 3, "了解比较或体验反馈，继续处理重点顾虑，不制造购买压力。", "您好，想跟进一下上次提到的【重点顾虑】是否已经有答案。如果您还在比较，我可以按相同使用任务帮您逐项核对；不急于现在决定，您按自己的节奏考虑即可。"),
    ("第7天", 7, "确认决策进度与后续意愿，尊重暂缓或停止联系的选择。", "您好，跟进一下上次咨询的电脑方案。您目前是准备近期购买、还需要补充信息，还是暂缓计划？我可以按您的节奏继续协助；如果暂时不需要跟进，也请告诉我，我会停止本轮联系。"),
]
CHANNELS = ("门店当面沟通", "微信", "电话", "短信", "邮件")
TASK_STATUSES = ("待联系", "已联系", "已解决", "已跳过")
PLAN_STATUSES = ("进行中", "已成交", "暂缓", "未成交", "停止联系")


def _as_date(value: date | str | None, field: str) -> date:
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        raise ValueError(f"{field} must be a date, not a datetime")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} must use YYYY-MM-DD") from exc
    raise ValueError(f"{field} must use YYYY-MM-DD")


def create_plan(
    start_date: date | str | None = None,
    label: str | None = None,
    channel: str = "微信",
    *,
    sequence: int = 1,
    plan_id: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Create an anonymous four-touch plan without storing customer identity."""
    start = _as_date(start_date, "start_date")
    if channel not in CHANNELS:
        raise ValueError("联系渠道无效")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise ValueError("sequence must be a positive integer")
    cleaned_label = (label or f"线索-{start:%Y%m%d}-{sequence:03d}").strip()
    if not cleaned_label or len(cleaned_label) > 64 or "\n" in cleaned_label or "\r" in cleaned_label:
        raise ValueError("线索代号不能为空且不得超过 64 个字符")
    return {
        "id": plan_id or uuid.uuid4().hex,
        "label": cleaned_label,
        "start_date": start.isoformat(),
        "status": "进行中",
        "created_at": (created_at or datetime.now()).isoformat(timespec="seconds"),
        "tasks": [
            {
                "title": title,
                "date": (start + timedelta(days=offset)).isoformat(),
                "purpose": purpose,
                "message": message,
                "channel": channel,
                "status": "待联系",
                "note": "",
            }
            for title, offset, purpose, message in STAGES
        ],
    }


def task_due_label(task: Mapping[str, Any], today: date | str | None = None) -> str:
    status = task.get("status")
    if status != "待联系":
        return str(status or "状态未知")
    due = _as_date(task.get("date"), "task date")
    current = _as_date(today, "today")
    if due < current:
        return "逾期"
    if due == current:
        return "今日待联系"
    return "待到期"


def update_task(
    plan: dict[str, Any],
    task_number: int,
    *,
    status: str | None = None,
    date_value: date | str | None = None,
    channel: str | None = None,
    message: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Validate and apply edits to one 1-based task in a plan."""
    if isinstance(task_number, bool) or not isinstance(task_number, int):
        raise ValueError("task_number must be an integer from 1 to 4")
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not 1 <= task_number <= len(tasks):
        raise ValueError("节点序号无效")
    task = tasks[task_number - 1]
    if not isinstance(task, dict):
        raise ValueError("跟进节点格式错误")
    if status is not None:
        if status not in TASK_STATUSES:
            raise ValueError("联系状态无效")
        task["status"] = status
    if date_value is not None:
        task["date"] = _as_date(date_value, "task date").isoformat()
    if channel is not None:
        if channel not in CHANNELS:
            raise ValueError("联系渠道无效")
        task["channel"] = channel
    if message is not None:
        task["message"] = _bounded_text(message, "话术", 2000)
    if note is not None:
        task["note"] = _bounded_text(note, "联系结果", 500)
    return plan


def update_plan_status(plan: dict[str, Any], status: str) -> dict[str, Any]:
    if status not in PLAN_STATUSES:
        raise ValueError("线索状态无效")
    plan["status"] = status
    return plan


def _bounded_text(value: str, name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name}必须是文本")
    cleaned = value.strip()
    if len(cleaned) > limit:
        raise ValueError(f"{name}不能超过 {limit} 个字符")
    return cleaned


def load_plans(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取跟进数据：{path}") from exc
    if not isinstance(data, list) or any(not isinstance(plan, dict) for plan in data):
        raise ValueError(f"跟进数据格式错误：{path}")
    return data


def save_plans(path: Path, plans: list[dict[str, Any]]) -> None:
    if not isinstance(plans, list) or any(not isinstance(plan, dict) for plan in plans):
        raise ValueError("跟进数据必须是计划对象列表")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(plans, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
