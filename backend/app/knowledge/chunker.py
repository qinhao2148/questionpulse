"""Chunk parsed sections into retrieval-friendly pieces.

Strategy: one chunk per section when it fits; longer sections are split on
paragraph boundaries to the token budget. Every chunk carries the document
title and section path so short passages stay semantically complete, and the
stable logical key (document_key/section/slug-index) lets a new version diff
against the old one and reuse unchanged vectors.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

TARGET_TOKENS = 400
MAX_TOKENS = 600

_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class PreparedChunk:
    logical_chunk_key: str
    chunk_index: int
    section_path: str
    page_start: int | None
    page_end: int | None
    content: str
    content_sha256: str
    token_count: int


def approx_token_count(text: str) -> int:
    """Rough token estimate: CJK chars count ~1 token, others ~1 per 4 chars."""
    cjk = sum(1 for ch in text if unicodedata.east_asian_width(ch) in ("W", "F"))
    return cjk + (len(text) - cjk) // 4 + 1


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).strip().lower()
    text = _WHITESPACE_RE.sub("-", text)
    return text[:60] or "section"


def _split_long_text(text: str, max_tokens: int) -> list[str]:
    if approx_token_count(text) <= max_tokens:
        return [text]
    paragraphs = [p.strip() for p in re.split(r"\n{2,}|\n", text) if p.strip()]
    if len(paragraphs) <= 1:
        # No paragraph structure: hard-split by character windows.
        window = max_tokens * 2
        return [text[i : i + window] for i in range(0, len(text), window)]
    parts: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for paragraph in paragraphs:
        tokens = approx_token_count(paragraph)
        if current and current_tokens + tokens > max_tokens:
            parts.append("\n".join(current))
            current, current_tokens = [], 0
        if tokens > max_tokens:
            if current:
                parts.append("\n".join(current))
                current, current_tokens = [], 0
            parts.extend(_split_long_text(paragraph, max_tokens))
            continue
        current.append(paragraph)
        current_tokens += tokens
    if current:
        parts.append("\n".join(current))
    return parts


def build_chunks(
    document_key: str,
    document_title: str,
    sections: list,
) -> list[PreparedChunk]:
    """Turn parser sections into version-agnostic chunks.

    ``sections`` items are ``app.knowledge.parser.ParsedSection``.
    """
    chunks: list[PreparedChunk] = []
    section_counters: dict[str, int] = {}
    for section in sections:
        section_path = "/".join(part for part in section.title_path if part)
        base_key = f"{document_key}/{_slug(section_path)}"
        pieces = _split_long_text(section.text, MAX_TOKENS)
        # Merge tiny trailing pieces back together to avoid one-line chunks.
        merged: list[str] = []
        for piece in pieces:
            if merged and (
                approx_token_count(merged[-1]) < TARGET_TOKENS // 2
                and approx_token_count(piece) < TARGET_TOKENS // 2
            ):
                merged[-1] = f"{merged[-1]}\n{piece}"
            else:
                merged.append(piece)
        for piece in merged:
            ordinal = section_counters.get(base_key, 0)
            section_counters[base_key] = ordinal + 1
            contextualized = (
                f"文档：{document_title}\n章节：{section_path}\n内容：{piece}"
            )
            chunks.append(
                PreparedChunk(
                    logical_chunk_key=f"{base_key}/{ordinal}",
                    chunk_index=len(chunks),
                    section_path=section_path,
                    page_start=section.page_start,
                    page_end=section.page_end,
                    content=contextualized,
                    content_sha256=hashlib.sha256(contextualized.encode("utf-8")).hexdigest(),
                    token_count=approx_token_count(contextualized),
                )
            )
    return chunks
