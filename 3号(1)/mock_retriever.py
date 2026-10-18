"""Offline mock retriever backed by curated local knowledge-base excerpts.

This module deliberately does not pretend to be teammate 2's production index. It
is an offline demo implementation that reads a small, auditable set of Markdown
files and ranks their excerpts with deterministic token overlap.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_KB_ROOT = (
    PROJECT_ROOT
    / ".huawei-kb-review-session"
    / "华为PC全板块深度知识库_v7"
)

# These are real files observed during the initial project audit. Keeping the
# list small makes the offline demo predictable and keeps citations auditable.
CURATED_DOCUMENTS = (
    Path("README.md"),
    Path("P1-产品参数库/04-华为商城销售款式/MateBook 14 鸿蒙版销售配置.md"),
    Path("P1-产品参数库/04-华为商城销售款式/商城在售款式快照.md"),
    Path("P2-卖点话术库/00-使用说明/话术事实边界.md"),
    Path("P5-培训赋能库/07-销售培训/销售对话演练指引.md"),
    Path("P5-培训赋能库/06-测验/销售顾问自测题.md"),
)

_URL_RE = re.compile(r"https?://[^\s)\]>]+", re.IGNORECASE)
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_STOP_BIGRAMS = {
    "哪些",
    "什么",
    "如何",
    "怎么",
    "是否",
    "可以",
    "需要",
    "当前",
    "知识",
    "资料",
    "问题",
    "请问",
    "这个",
    "那个",
    "以及",
}


@dataclass(frozen=True)
class MockDocument:
    """One searchable excerpt and its local citation metadata."""

    text: str
    source: str
    local_path: str | None = None
    url: str | None = None
    section: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    demo: bool = True

    def as_result(self, score: float) -> dict[str, Any]:
        return {
            "text": self.text,
            "source": self.source,
            "url": self.url,
            "page": None,
            "score": round(score, 4),
            "section": self.section,
            "local_path": self.local_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "demo": self.demo,
        }


def _tokenize(value: str) -> set[str]:
    """Create deterministic ASCII-token and Chinese-bigram features."""

    lowered = value.lower()
    tokens = set(_ASCII_TOKEN_RE.findall(lowered))
    cjk_chars = _CJK_RE.findall(lowered)
    for index in range(len(cjk_chars) - 1):
        bigram = "".join(cjk_chars[index : index + 2])
        if bigram not in _STOP_BIGRAMS:
            tokens.add(bigram)
    return tokens


def _first_url(text: str) -> str | None:
    match = _URL_RE.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,;:，。；：")


def _split_excerpts(content: str) -> Iterable[tuple[str, str, int, int]]:
    """Yield (section, text, start_line, end_line) for readable excerpts."""

    lines = content.splitlines()
    heading = "文档正文"
    section_start = 1
    body: list[tuple[int, str]] = []

    def flush_section(
        current_heading: str,
        current_body: list[tuple[int, str]],
        start_line: int,
        end_line: int,
    ) -> Iterable[tuple[str, str, int, int]]:
        paragraphs: list[tuple[int, int, str]] = []
        paragraph_lines: list[tuple[int, str]] = []

        def flush_paragraph() -> None:
            if not paragraph_lines:
                return
            start = paragraph_lines[0][0]
            end = paragraph_lines[-1][0]
            text = " ".join(line.strip() for _, line in paragraph_lines).strip()
            if text:
                paragraphs.append((start, end, text))
            paragraph_lines.clear()

        for line_number, line in current_body:
            if not line.strip():
                flush_paragraph()
            else:
                paragraph_lines.append((line_number, line))
        flush_paragraph()

        if not paragraphs and current_body:
            text = " ".join(line.strip() for _, line in current_body).strip()
            if text:
                paragraphs.append((start_line, end_line, text))

        # A long section is still returned as bounded chunks so the UI stays
        # readable and each citation remains useful.
        chunk_text = ""
        chunk_start = 0
        chunk_end = 0
        for paragraph_start, paragraph_end, paragraph in paragraphs:
            if chunk_text and len(chunk_text) + len(paragraph) + 1 > 1200:
                yield current_heading, chunk_text, chunk_start, chunk_end
                chunk_text = ""
            if not chunk_text:
                chunk_start = paragraph_start
            chunk_text = f"{chunk_text} {paragraph}".strip()
            chunk_end = paragraph_end
        if chunk_text:
            yield current_heading, chunk_text, chunk_start, chunk_end

    for line_number, line in enumerate(lines, start=1):
        if line.startswith("#") and line.lstrip().startswith("#"):
            if body:
                yield from flush_section(heading, body, section_start, line_number - 1)
            heading = line.lstrip("#").strip() or "文档正文"
            section_start = line_number + 1
            body = []
        else:
            body.append((line_number, line))

    if body:
        yield from flush_section(heading, body, section_start, len(lines))


def _load_documents(kb_root: Path) -> list[MockDocument]:
    documents: list[MockDocument] = []
    for relative_path in CURATED_DOCUMENTS:
        path = kb_root / relative_path
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            LOGGER.warning("Curated knowledge-base file is missing: %s", path)
            continue
        except OSError:
            LOGGER.exception("Could not read curated knowledge-base file: %s", path)
            continue

        for section, text, line_start, line_end in _split_excerpts(content):
            if len(text.strip()) < 35:
                continue
            documents.append(
                MockDocument(
                    text=text,
                    source=relative_path.name,
                    local_path=relative_path.as_posix(),
                    url=_first_url(text),
                    section=section,
                    line_start=line_start,
                    line_end=line_end,
                )
            )
    return documents


def _fallback_documents() -> list[MockDocument]:
    """Keep the UI demonstrable if a deployment omits the source folder."""

    return [
        MockDocument(
            text=(
                "在 2026-10-17 的指定商城页面快照中，MateBook 14 鸿蒙版记录为 "
                "14.2 英寸 OLED、2880×1920、3:2、多点触控，电池为 70Wh 额定容量，"
                "重量约 1.33kg（含电池）。这是历史快照，不代表当前销售状态。"
            ),
            source="[Mock 内置演示] MateBook 14 鸿蒙版销售配置",
            url="https://consumer.huawei.com/cn/harmonyos-computer/matebook-14-harmonyos-version/specs/",
            section="内置演示片段：历史页面基础信息",
        ),
        MockDocument(
            text=(
                "2026-10-17 商城专区快照展示过 MateBook Pro 麒麟 X90 Plus、"
                "MateBook Pro、MateBook Pro S、MateBook Fold 非凡大师麒麟 X90 Plus、"
                "HUAWEI MateBook Fold 非凡大师和 MateBook 14 鸿蒙版。专区展示不证明库存。"
            ),
            source="[Mock 内置演示] 华为商城电脑在售款式快照",
            url="https://m.vmall.com/portal/activity/index.html?isShowLayout=false&pn=pczq",
            section="内置演示片段：专区展示记录",
        ),
        MockDocument(
            text=(
                "连接扩展坞前需要取得电脑完整型号、具体端口、扩展坞型号、供电、"
                "显示器和外设需求，再查两端官方规格并用目标线缆与显示器验证；"
                "接口能插入不代表数据、视频和供电都支持。"
            ),
            source="[Mock 内置演示] 销售顾问自测题",
            section="内置演示片段：扩展坞核验",
        ),
        MockDocument(
            text=(
                "专业软件迁移前应取得准确的软件版本、插件、文件格式、外设和许可，"
                "查应用开发者支持，并用脱敏样本测试安装、登录、编辑、保存、导出及外设；"
                "验证通过前保留旧工作路径。"
            ),
            source="[Mock 内置演示] 销售对话演练指引",
            section="内置演示片段：专业软件与系统路线",
        ),
    ]


class LocalMockRetriever:
    """Small deterministic retriever used until teammate 2 delivers an index."""

    def __init__(self, kb_root: str | os.PathLike[str] | None = None) -> None:
        configured_root = kb_root or os.environ.get("KB_ROOT")
        self.kb_root = Path(configured_root) if configured_root else DEFAULT_KB_ROOT
        self.documents = _load_documents(self.kb_root)
        self.using_fallback = not self.documents
        if self.using_fallback:
            self.documents = _fallback_documents()
            LOGGER.warning(
                "Knowledge-base excerpts were unavailable; using built-in Mock demo records."
            )

    def search(self, query: str, top_k: int = 5) -> dict[str, list[dict[str, Any]]]:
        query = str(query).strip()
        if not query:
            raise ValueError("query must not be empty")
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 20:
            raise ValueError("top_k must be an integer between 1 and 20")

        query_tokens = _tokenize(query)
        if not query_tokens:
            return {"results": []}

        scored: list[tuple[float, int, MockDocument]] = []
        for index, document in enumerate(self.documents):
            document_tokens = _tokenize(document.text)
            overlap = len(query_tokens & document_tokens)
            if not overlap:
                continue
            score = overlap / max(len(query_tokens), 1)
            normalized_query = re.sub(r"\s+", "", query.lower())
            normalized_text = re.sub(r"\s+", "", document.text.lower())
            if len(normalized_query) >= 4 and normalized_query in normalized_text:
                score += 0.12
            scored.append((min(score, 1.0), index, document))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return {
            "results": [
                document.as_result(score)
                for score, _, document in scored[:top_k]
                if score >= 0.12
            ]
        }


def get_default_retriever() -> LocalMockRetriever:
    """Create a fresh retriever so a changed KB_ROOT is honored per process."""

    return LocalMockRetriever()


def retrieve(payload: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Expose the future teammate-compatible payload contract for the Mock mode."""

    if not isinstance(payload, Mapping):
        raise TypeError("retrieval payload must be a mapping")
    query = payload.get("query")
    top_k = payload.get("top_k", 5)
    if not isinstance(query, str):
        raise TypeError("payload.query must be a string")
    return get_default_retriever().search(query, top_k=top_k)
