"""Shared view helpers for RAG citations (used by routes and snapshots)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    RagCitation,
)
from app.schemas.knowledge import CitationView


def format_location(
    document_title: str,
    version_number: int,
    section_path: str | None,
    page_start: int | None,
    page_end: int | None,
) -> str:
    parts = [f"《{document_title}》v{version_number}"]
    if section_path:
        parts.append(section_path)
    if page_start:
        page = f"第{page_start}页" + (
            f"-{page_end}页" if page_end and page_end != page_start else ""
        )
        parts.append(page)
    return " · ".join(parts)


async def citation_views(
    db: AsyncSession, citations: list[RagCitation]
) -> list[CitationView]:
    """Citations store chunk ids; hydrate document title/version/page for UI."""
    if not citations:
        return []
    chunk_ids = [c.chunk_id for c in citations]
    version_ids = {c.document_version_id for c in citations if c.document_version_id}
    chunks: dict[str, KnowledgeChunk] = {}
    if chunk_ids:
        rows = await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.id.in_(chunk_ids)))
        chunks = {chunk.id: chunk for chunk in rows.scalars().all()}
    version_map: dict[str, tuple[str, int]] = {}
    if version_ids:
        rows = await db.execute(
            select(KnowledgeDocumentVersion, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeDocumentVersion.document_id)
            .where(KnowledgeDocumentVersion.id.in_(version_ids))
        )
        version_map = {
            version.id: (document.title, version.version_number)
            for version, document in rows.all()
        }
    views = []
    for citation in citations:
        chunk = chunks.get(citation.chunk_id)
        title, version_number = version_map.get(citation.document_version_id, ("未知文档", 1))
        section = chunk.section_path if chunk else None
        page_start = chunk.page_start if chunk else None
        page_end = chunk.page_end if chunk else None
        views.append(
            CitationView(
                chunk_id=citation.chunk_id,
                document_title=title,
                version_number=version_number,
                section_path=section,
                page_start=page_start,
                page_end=page_end,
                score=citation.retrieval_score,
                location=format_location(title, version_number, section, page_start, page_end),
                content=citation.quoted_text or "",
            )
        )
    return views
