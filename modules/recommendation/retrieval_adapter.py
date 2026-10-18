"""Adapter between the Gradio app and the pending teammate retriever.

Teammate 2 has not delivered an implementation yet. The default mode is therefore
an explicitly labelled local Mock retriever. The team mode is intentionally a
small dynamic import boundary so the UI does not need to change when the real
function arrives.
"""

from __future__ import annotations

import importlib
import logging
import math
import os
from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any, Callable
from urllib.parse import urlparse

LOGGER = logging.getLogger(__name__)
DEFAULT_TOP_K = 5
MAX_TOP_K = 20


class RetrievalAdapterError(Exception):
    """Base class for user-safe retrieval errors."""


class RetrievalConfigurationError(RetrievalAdapterError):
    """The selected retriever mode is not configured."""


class RetrievalServiceError(RetrievalAdapterError):
    """The configured retriever raised while serving a query."""


class MalformedRetrievalResponse(RetrievalAdapterError):
    """The retriever returned a response outside the agreed contract."""


class TeamRetrieverNotConfigured(RetrievalConfigurationError):
    """Team mode was selected before teammate 2 delivered an importable function."""


@dataclass(frozen=True)
class RetrievalItem:
    text: str
    source: str
    url: str | None = None
    page: str | int | None = None
    score: float | None = None
    section: str | None = None
    local_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    demo: bool = False
    source_id: str | None = None
    product_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalResponse:
    mode: str
    results: list[RetrievalItem]
    warnings: list[str]


def get_mode(mode: str | None = None) -> str:
    selected = (mode or os.environ.get("RETRIEVER_MODE", "mock")).strip().lower()
    if selected in {"mock", "demo", "offline"}:
        return "mock"
    if selected in {"team", "real", "production"}:
        return "team"
    raise RetrievalConfigurationError(
        "RETRIEVER_MODE must be 'mock' or 'team'"
    )


def mode_label(mode: str | None = None) -> str:
    selected = get_mode(mode)
    if selected == "mock":
        return "Mock 演示模式（本地知识库精选片段，无外部 API）"
    return "真实检索模式（通过适配层）"


def _validate_top_k(top_k: int) -> int:
    if isinstance(top_k, bool) or not isinstance(top_k, int):
        raise ValueError("top_k must be an integer")
    if not 1 <= top_k <= MAX_TOP_K:
        raise ValueError(f"top_k must be between 1 and {MAX_TOP_K}")
    return top_k


def _as_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_url(value: Any) -> str | None:
    candidate = _as_optional_text(value)
    if not candidate:
        return None
    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return candidate


def _as_score(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(score):
        return None
    return max(0.0, min(score, 1.0))


def _as_optional_line(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        line = int(value)
    except (TypeError, ValueError):
        return None
    return line if line > 0 else None


def _first_value(item: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


_PRODUCT_METADATA_KEYS = {
    "product_name", "product_title", "product_id", "product_model", "model", "sku", "sbom_code",
    "category", "product_category", "features", "functions", "key_features",
    "specifications", "specs", "attributes", "facts", "processor", "cpu",
    "memory", "ram", "storage", "operating_system", "os", "screen", "display",
    "battery", "weight", "price", "currency", "scenarios", "use_cases",
    "compatibility", "compatible_with", "limitations", "restrictions", "warranty",
    "service", "support", "delivery", "型号", "产品类别", "类别", "主要功能",
    "功能", "处理器", "内存", "存储", "操作系统", "系统", "屏幕", "显示屏",
    "电池", "重量", "价格", "售价", "币种", "适用场景", "场景", "兼容性",
    "使用限制", "限制", "保修", "质保", "服务", "交付",
}


def _product_metadata(item: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only product identity and fact fields from structured retriever output."""

    result: dict[str, Any] = {}
    for container_key in ("product", "product_metadata", "metadata"):
        nested = item.get(container_key)
        if isinstance(nested, Mapping):
            for key, value in nested.items():
                if str(key).lower() in _PRODUCT_METADATA_KEYS and value not in (None, ""):
                    result[str(key)] = value
    for key, value in item.items():
        if str(key).lower() in _PRODUCT_METADATA_KEYS and value not in (None, ""):
            result[str(key)] = value
    return result


def normalize_response(
    raw: Any,
    *,
    mode: str,
    demo: bool,
) -> RetrievalResponse:
    """Map common result aliases into one safe response shape.

    Expected team payload:
        {"results": [{"text": ..., "source": ..., "url": ..., ...}]}

    Aliases are accepted for integration tolerance, but no missing content is
    invented. Items without text are ignored and recorded as warnings.
    """

    if not isinstance(raw, Mapping):
        raise MalformedRetrievalResponse("retriever response must be a mapping")
    raw_results = raw.get("results")
    if raw_results is None:
        raise MalformedRetrievalResponse("retriever response must contain results")
    if not isinstance(raw_results, (list, tuple)):
        raise MalformedRetrievalResponse("retriever results must be a list")

    results: list[RetrievalItem] = []
    warnings: list[str] = []
    for index, raw_item in enumerate(raw_results, start=1):
        if not isinstance(raw_item, Mapping):
            warnings.append(f"第 {index} 条结果格式无效，已忽略")
            continue

        text = _as_optional_text(_first_value(raw_item, "text", "content", "snippet"))
        if not text:
            warnings.append(f"第 {index} 条结果缺少文本片段，已忽略")
            continue

        source = _as_optional_text(
            _first_value(
                raw_item,
                "source",
                "title",
                "file_name",
                "filename",
                "local_path",
                "path",
            )
        )
        if not source:
            source = "来源未提供"
            warnings.append(f"第 {index} 条结果缺少来源字段")

        raw_url = _first_value(raw_item, "url", "link", "href")
        url = _as_url(raw_url)
        if raw_url not in (None, "") and url is None:
            warnings.append(f"第 {index} 条结果的来源链接无效，已按本地来源展示")

        results.append(
            RetrievalItem(
                text=text,
                source=source,
                url=url,
                page=_first_value(raw_item, "page", "page_number"),
                score=_as_score(_first_value(raw_item, "score", "similarity")),
                section=_as_optional_text(
                    _first_value(raw_item, "section", "chapter", "heading")
                ),
                local_path=_as_optional_text(
                    _first_value(raw_item, "local_path", "path", "file")
                ),
                line_start=_as_optional_line(raw_item.get("line_start")),
                line_end=_as_optional_line(raw_item.get("line_end")),
                demo=bool(raw_item.get("demo", demo)),
                source_id=_as_optional_text(
                    _first_value(raw_item, "source_id", "document_id", "doc_id", "chunk_id", "item_id", "id")
                ),
                product_metadata=_product_metadata(raw_item),
            )
        )

    return RetrievalResponse(mode=mode, results=results, warnings=warnings)


def _load_team_retriever() -> Callable[[dict[str, Any]], Any]:
    module_name = os.environ.get("TEAM_RETRIEVER_MODULE", "").strip()
    function_name = os.environ.get("TEAM_RETRIEVER_FUNCTION", "retrieve").strip()
    if not module_name:
        raise TeamRetrieverNotConfigured(
            "2 号检索接口尚未交付，请配置 TEAM_RETRIEVER_MODULE 和 TEAM_RETRIEVER_FUNCTION"
        )

    try:
        module = importlib.import_module(module_name)
        function = getattr(module, function_name)
    except (ImportError, AttributeError) as exc:
        LOGGER.exception("Could not load teammate retriever")
        raise TeamRetrieverNotConfigured(
            "2 号检索接口未找到，请检查模块名和函数名配置"
        ) from exc
    if not callable(function):
        raise TeamRetrieverNotConfigured("2 号检索接口目标不是可调用函数")
    return function


def retrieve_with_adapter(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    *,
    mode: str | None = None,
    team_retriever: Callable[[dict[str, Any]], Any] | None = None,
) -> RetrievalResponse:
    """Retrieve through Mock or the future teammate function.

    The real interface call, once delivered, must be a local callable accepting
    ``{"query": query, "top_k": top_k}`` and returning
    ``{"results": [{"text": ..., "source": ..., ...}]}``.
    """

    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    top_k = _validate_top_k(top_k)
    selected_mode = get_mode(mode)
    payload = {"query": query.strip(), "top_k": top_k}

    if selected_mode == "mock":
        from .mock_retriever import retrieve as mock_retrieve

        try:
            raw = mock_retrieve(payload)
        except Exception as exc:  # pragma: no cover - defensive boundary
            LOGGER.exception("Mock retriever failed")
            raise RetrievalServiceError("mock retriever failed") from exc
        return normalize_response(raw, mode="mock", demo=True)

    function = team_retriever or _load_team_retriever()
    try:
        raw = function(payload)
    except Exception as exc:
        LOGGER.exception("Teammate retriever failed")
        raise RetrievalServiceError("teammate retriever failed") from exc
    return normalize_response(raw, mode="team", demo=False)


# Short alias for callers that want the adapter name to read naturally.
retrieve = retrieve_with_adapter
