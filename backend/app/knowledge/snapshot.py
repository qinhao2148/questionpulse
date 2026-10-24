"""Classroom knowledge bindings and lazily-frozen snapshots.

A binding is the teacher's intent (which knowledge base / documents). The
snapshot is the resolved set of concrete document versions — always the
document's current version at resolution time, never every historical ready
version. Snapshots rebuild on every binding change but are frozen by the
first real RAG retrieval, so answers never silently change material
mid-class, and later document updates never leak into a frozen classroom.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import (
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    SessionKnowledgeBinding,
    SessionKnowledgeSnapshot,
    SessionKnowledgeSnapshotItem,
)


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def list_bindings(session: AsyncSession, session_id: str) -> list[SessionKnowledgeBinding]:
    result = await session.execute(
        select(SessionKnowledgeBinding)
        .where(SessionKnowledgeBinding.session_id == session_id)
        .order_by(SessionKnowledgeBinding.created_at)
    )
    return list(result.scalars().all())


async def _resolve_version_ids(
    session: AsyncSession, bindings: list[SessionKnowledgeBinding]
) -> list[str]:
    """Resolve bindings to exactly one version per document: the current one.

    Querying every ready version instead would make classrooms retrieve
    superseded policies alongside the effective one, so deprecated content
    could be cited in answers.
    """
    document_ids: list[str] = []
    seen_documents: set[str] = set()
    for binding in bindings:
        if binding.binding_scope == "whole_knowledge_base":
            result = await session.execute(
                select(KnowledgeDocument.id).where(
                    KnowledgeDocument.knowledge_base_id == binding.knowledge_base_id,
                    KnowledgeDocument.status == "active",
                    KnowledgeDocument.current_version_id.is_not(None),
                )
            )
            candidates = [row[0] for row in result.all()]
        elif binding.document_id:
            candidates = [binding.document_id]
        else:
            continue
        for document_id in candidates:
            if document_id not in seen_documents:
                seen_documents.add(document_id)
                document_ids.append(document_id)
    if not document_ids:
        return []
    # Verify the binding scope actually covers each document (single_document
    # bindings must not leak unrelated documents from the same base).
    allowed: set[str] = set()
    for binding in bindings:
        if binding.binding_scope == "whole_knowledge_base":
            result = await session.execute(
                select(KnowledgeDocument.id).where(
                    KnowledgeDocument.knowledge_base_id == binding.knowledge_base_id
                )
            )
            allowed.update(row[0] for row in result.all())
        elif binding.document_id:
            allowed.add(binding.document_id)
    result = await session.execute(
        select(KnowledgeDocument.id, KnowledgeDocument.current_version_id).where(
            KnowledgeDocument.id.in_(document_ids),
            KnowledgeDocument.status == "active",
            KnowledgeDocument.current_version_id.is_not(None),
        )
    )
    version_ids: list[str] = []
    seen_versions: set[str] = set()
    for document_id, current_version_id in result.all():
        if document_id not in allowed:
            continue
        # current_version_id points at a published (ready) version by design:
        # the pointer only moves in the atomic publish step after indexing.
        if current_version_id not in seen_versions:
            seen_versions.add(current_version_id)
            version_ids.append(current_version_id)
    return version_ids


async def resolve_snapshot_version_ids(
    session: AsyncSession, session_id: str
) -> tuple[list[str], SessionKnowledgeSnapshot | None]:
    """Return the version ids the classroom may read, creating/refreshing the
    snapshot row while it is still unfrozen. A frozen snapshot is immutable:
    later uploads must never change what a started classroom retrieves."""
    bindings = await list_bindings(session, session_id)
    if not bindings:
        return [], None

    result = await session.execute(
        select(SessionKnowledgeSnapshot)
        .where(SessionKnowledgeSnapshot.session_id == session_id)
        .order_by(SessionKnowledgeSnapshot.created_at.desc())
        .limit(1)
    )
    snapshot = result.scalars().first()
    frozen = bool(snapshot and snapshot.frozen_at)
    needs_rebuild = snapshot is None or not frozen

    if needs_rebuild:
        version_ids = await _resolve_version_ids(session, bindings)
        if snapshot is None:
            snapshot = SessionKnowledgeSnapshot(
                session_id=session_id, status="active"
            )
            session.add(snapshot)
            await session.flush()
        await session.execute(
            SessionKnowledgeSnapshotItem.__table__.delete().where(
                SessionKnowledgeSnapshotItem.snapshot_id == snapshot.id
            )
        )
        for version_id in version_ids:
            session.add(
                SessionKnowledgeSnapshotItem(
                    snapshot_id=snapshot.id, document_version_id=version_id
                )
            )
        await session.commit()

    result = await session.execute(
        select(SessionKnowledgeSnapshotItem.document_version_id).where(
            SessionKnowledgeSnapshotItem.snapshot_id == snapshot.id
        )
    )
    version_ids = [row[0] for row in result.all()]
    return version_ids, snapshot


async def freeze_snapshot(session: AsyncSession, snapshot: SessionKnowledgeSnapshot) -> None:
    """Lock the snapshot permanently; called by the first real retrieval."""
    if snapshot.frozen_at is None:
        snapshot.frozen_at = _utcnow_naive()
        await session.commit()


async def rebuild_snapshot(
    session: AsyncSession, session_id: str
) -> SessionKnowledgeSnapshot | None:
    """Recompute the snapshot now, clearing the freeze (binding edit path)."""
    await session.execute(
        SessionKnowledgeSnapshot.__table__.delete().where(
            SessionKnowledgeSnapshot.session_id == session_id
        )
    )
    bindings = await list_bindings(session, session_id)
    if not bindings:
        await session.commit()
        return None
    version_ids = await _resolve_version_ids(session, bindings)
    snapshot = SessionKnowledgeSnapshot(session_id=session_id, status="active")
    session.add(snapshot)
    await session.flush()
    for version_id in version_ids:
        session.add(
            SessionKnowledgeSnapshotItem(
                snapshot_id=snapshot.id, document_version_id=version_id
            )
        )
    await session.commit()
    return snapshot


async def snapshot_documents(
    session: AsyncSession, snapshot: SessionKnowledgeSnapshot | None
) -> list[dict]:
    """Describe the snapshot for teacher UI: title, version number, status."""
    if snapshot is None:
        return []
    result = await session.execute(
        select(KnowledgeDocumentVersion, KnowledgeDocument)
        .join(
            SessionKnowledgeSnapshotItem,
            SessionKnowledgeSnapshotItem.document_version_id == KnowledgeDocumentVersion.id,
        )
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeDocumentVersion.document_id)
        .where(SessionKnowledgeSnapshotItem.snapshot_id == snapshot.id)
        .order_by(KnowledgeDocument.title)
    )
    descriptions: list[dict] = []
    for version, document in result.all():
        descriptions.append(
            {
                "document_id": document.id,
                "document_title": document.title,
                "document_key": document.document_key,
                "document_version_id": version.id,
                "version_number": version.version_number,
                "status": version.status,
                "chunk_count": version.chunk_count,
                "embedding_model": version.embedding_model,
                "published_at": version.published_at.isoformat() if version.published_at else None,
            }
        )
    return descriptions


async def version_titles_for(
    session: AsyncSession, version_ids: list[str]
) -> dict[str, dict]:
    """Map version id -> {document_title, version_number} for citations."""
    if not version_ids:
        return {}
    result = await session.execute(
        select(KnowledgeDocumentVersion, KnowledgeDocument)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeDocumentVersion.document_id)
        .where(KnowledgeDocumentVersion.id.in_(version_ids))
    )
    mapping: dict[str, dict] = {}
    for version, document in result.all():
        mapping[version.id] = {
            "document_title": document.title,
            "version_number": version.version_number,
        }
    return mapping
