"""Lightweight document parsers producing a uniform section tree.

Each parser returns a flat list of :class:`ParsedSection` with a title path,
page numbers and plain text. The parser abstraction exists so Docling (or any
heavier parser) can replace these implementations later without touching the
chunking/indexing code. Formats: pdf, docx, pptx, md, txt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

PARSER_NAME = "lightweight"
PARSER_VERSION = "1"

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".md", ".markdown", ".txt"}


class ParseError(Exception):
    pass


@dataclass
class ParsedSection:
    title_path: list[str]
    text: str
    page_start: int | None = None
    page_end: int | None = None


@dataclass
class ParsedDocument:
    title: str
    sections: list[ParsedSection] = field(default_factory=list)


def _clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_pdf(path: Path) -> ParsedDocument:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if not reader.pages:
        raise ParseError("pdf_no_pages")
    doc = ParsedDocument(title=path.stem)
    current_title_path: list[str] = []
    buffer: list[str] = []
    section_start_page = 1

    def flush(end_page: int) -> None:
        text = _clean_text("\n".join(buffer))
        if text:
            doc.sections.append(
                ParsedSection(
                    title_path=current_title_path or [path.stem],
                    text=text,
                    page_start=section_start_page,
                    page_end=end_page,
                )
            )
        buffer.clear()

    for index, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - a broken page must not kill the doc
            page_text = ""
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        for line in lines:
            # Font-size signals are unavailable in plain pypdf extraction, so a
            # short numbered line ("第三章", "3.2 xxx") is treated as a heading.
            if (
                re.match(
                    r"^(第[一二三四五六七八九十百\d]+[章节篇部分]|[一二三四五六七八九十]+、|\d+(\.\d+){0,3}[\s、．.])",
                    line,
                )
                and len(line) <= 60
            ):
                flush(index)
                current_title_path = [line]
                section_start_page = index
            else:
                buffer.append(line)
    flush(len(reader.pages))
    if not doc.sections:
        raise ParseError("pdf_no_text")
    return doc


def parse_docx(path: Path) -> ParsedDocument:
    import docx

    document = docx.Document(str(path))
    doc = ParsedDocument(title=path.stem)
    # Heading chain, e.g. ["员工手册", "第三章 年假", "申请流程"].
    heading_chain: list[str] = [path.stem]
    buffer: list[str] = []

    def flush() -> None:
        text = _clean_text("\n".join(buffer))
        if text:
            doc.sections.append(ParsedSection(title_path=list(heading_chain), text=text))
        buffer.clear()

    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name or "").lower()
        level = None
        if "heading" in style or "标题" in style:
            digits = re.findall(r"\d+", style)
            if digits:
                level = int(digits[0])
            level = level or 1
        if level is not None:
            flush()
            # Depth 1 resets the chain; deeper levels replace their own slot,
            # with empty placeholders when a shallow heading was skipped.
            if len(heading_chain) < level + 1:
                heading_chain += [""] * (level + 1 - len(heading_chain))
            heading_chain[level] = text
        else:
            buffer.append(text)
    flush()
    for table in document.tables:
        rows = []
        for row in table.rows:
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            rows.append(" | ".join(cells))
        table_text = _clean_text("\n".join(rows))
        if table_text:
            doc.sections.append(
                ParsedSection(title_path=[path.stem, "表格"], text=table_text)
            )
    if not doc.sections:
        raise ParseError("docx_no_text")
    return doc


def parse_pptx(path: Path) -> ParsedDocument:
    from pptx import Presentation

    presentation = Presentation(str(path))
    doc = ParsedDocument(title=path.stem)
    for slide_number, slide in enumerate(presentation.slides, start=1):
        title = ""
        body: list[str] = []
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            text = shape.text_frame.text.strip()
            if not text:
                continue
            if shape == slide.shapes.title and not title:
                title = text
            else:
                body.append(text)
        combined = _clean_text("\n".join([title, *body]) if title else "\n".join(body))
        if combined:
            doc.sections.append(
                ParsedSection(
                    title_path=[path.stem, title or f"第{slide_number}页"],
                    text=combined,
                    page_start=slide_number,
                    page_end=slide_number,
                )
            )
    if not doc.sections:
        raise ParseError("pptx_no_text")
    return doc


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def parse_markdown(path: Path) -> ParsedDocument:
    raw = path.read_text(encoding="utf-8", errors="replace")
    doc = ParsedDocument(title=path.stem)
    # Heading chain: index i holds the level-(i+1) heading. A level-1 heading
    # becomes the document root so "handbook/员工手册/年假" never duplicates.
    heading_chain: list[str] = [path.stem]
    buffer: list[str] = []

    def flush() -> None:
        text = _clean_text("\n".join(buffer))
        if text:
            doc.sections.append(ParsedSection(title_path=list(heading_chain), text=text))
        buffer.clear()

    for line in raw.splitlines():
        heading = _HEADING_RE.match(line.strip())
        if heading:
            flush()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            if level == 1:
                doc.title = title
                heading_chain = [title]
                continue
            while len(heading_chain) < level:
                heading_chain.append("")
            heading_chain[level - 1] = title
            heading_chain = heading_chain[:level]
        else:
            buffer.append(line)
    flush()
    if not doc.sections:
        raise ParseError("md_no_text")
    return doc


def parse_text(path: Path) -> ParsedDocument:
    raw = path.read_text(encoding="utf-8", errors="replace")
    text = _clean_text(raw)
    if not text:
        raise ParseError("txt_empty")
    return ParsedDocument(title=path.stem, sections=[ParsedSection([path.stem], text)])


_PARSERS = {
    ".pdf": parse_pdf,
    ".docx": parse_docx,
    ".pptx": parse_pptx,
    ".md": parse_markdown,
    ".markdown": parse_markdown,
    ".txt": parse_text,
}


def parse_file(path: Path, suffix: str | None = None) -> ParsedDocument:
    suffix = (suffix or path.suffix).lower()
    parser = _PARSERS.get(suffix)
    if parser is None:
        raise ParseError(f"unsupported_format:{suffix}")
    return parser(path)
