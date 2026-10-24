"""Ingestion pipeline: parse -> chunk -> embed -> upsert -> atomic publish.

Sync implementation on purpose: parsing and embedding are CPU-bound and the
embedder is a synchronous ONNX model. Both the API process (via a background
thread) and the standalone worker call :func:`process_job`; the queued ->
running claim below is a compare-and-swap, so exactly one of them wins even
when both are watching the queue.
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.knowledge.chunker import build_chunks
from app.knowledge.embeddings import get_embedding_provider
from app.knowledge.parser import parse_file
from app.knowledge.vector_store import (
    KnowledgeVectorError,
    UpsertPoint,
    get_vector_store,
    new_point_id,
)
from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIngestionJob,
)

ALLOWED_MIME_PREFIXES = ("application/pdf", "application/vnd.openxmlformats", "text/")


class IngestionError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def utcnow() -> datetime:
    # Naive UTC to match the existing chat/table convention (DATETIME columns).
    return datetime.now(UTC).replace(tzinfo=None)


def storage_root(settings) -> Path:
    root = Path(settings.knowledge_storage_path)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / settings.knowledge_storage_path
    return root


def claim_job(session: Session, job_id: str, worker_id: str) -> bool:
    """CAS-claim one specific queued job. Exactly one claimer wins."""
    result = session.execute(
        update(KnowledgeIngestionJob)
        .where(KnowledgeIngestionJob.id == job_id, KnowledgeIngestionJob.status == "queued")
        .values(status="running", locked_by=worker_id, locked_at=utcnow(), started_at=utcnow())
    )
    session.commit()
    if result.rowcount != 1:
        return False
    job = session.get(KnowledgeIngestionJob, job_id)
    job.attempt_count = (job.attempt_count or 0) + 1
    session.commit()
    return True


def reclaim_stale_jobs(session: Session, settings) -> int:
    """Recover jobs whose worker crashed mid-run.

    A running job is a lease: past the lease duration it goes back to queued,
    or straight to dead once it has burned through the maximum attempts.
    Without this, a killed worker leaves the job running forever and the retry
    endpoint (which refuses running jobs) can never rescue it.
    """
    stale_before = utcnow() - timedelta(seconds=settings.knowledge_job_lease_seconds)
    max_attempts = settings.knowledge_job_max_attempts
    requeued = session.execute(
        update(KnowledgeIngestionJob)
        .where(
            KnowledgeIngestionJob.status == "running",
            KnowledgeIngestionJob.locked_at.is_not(None),
            KnowledgeIngestionJob.locked_at < stale_before,
            KnowledgeIngestionJob.attempt_count < max_attempts,
        )
        .values(status="queued", locked_by=None, locked_at=None)
    )
    dead = session.execute(
        update(KnowledgeIngestionJob)
        .where(
            KnowledgeIngestionJob.status == "running",
            KnowledgeIngestionJob.locked_at.is_not(None),
            KnowledgeIngestionJob.locked_at < stale_before,
            KnowledgeIngestionJob.attempt_count >= max_attempts,
        )
        .values(status="dead", locked_by=None,
                error_code="lease_expired",
                error_detail="worker lease expired after maximum attempts",
                finished_at=utcnow())
    )
    session.commit()
    return (requeued.rowcount or 0) + (dead.rowcount or 0)


def claim_next_job(session: Session, worker_id: str, settings=None) -> KnowledgeIngestionJob | None:
    """CAS-claim the oldest queued job; returns None when the queue is empty."""
    settings = settings or get_settings()
    reclaim_stale_jobs(session, settings)
    job = (
        session.execute(
            select(KnowledgeIngestionJob)
            .where(KnowledgeIngestionJob.status == "queued")
            .order_by(KnowledgeIngestionJob.created_at)
            .limit(1)
        )
        .scalars()
        .first()
    )
    if job is None:
        return None
    if not claim_job(session, job.id, worker_id):
        return None
    session.refresh(job)
    return job


def process_job(job_id: str, session: Session, settings=None) -> str:
    """Run one claimed job. Returns the final status string."""
    settings = settings or get_settings()
    job = session.get(KnowledgeIngestionJob, job_id)
    if job is None or job.status != "running":
        return "skipped"
    version = session.get(KnowledgeDocumentVersion, job.document_version_id)
    if version is None:
        _fail(session, job, version, "version_missing", "document version row disappeared")
        return "failed"
    document = session.get(KnowledgeDocument, version.document_id)
    if document is None:
        _fail(session, job, version, "document_missing", "document row disappeared")
        return "failed"
    try:
        if job.job_type == "purge":
            _purge_version(session, settings, version)
        else:
            _ingest_version(session, settings, document, version)
    except IngestionError as exc:
        _cleanup_partial_vectors(settings, version, job.job_type)
        _fail(session, job, version, exc.code, exc.detail)
        return "failed"
    except KnowledgeVectorError as exc:
        _cleanup_partial_vectors(settings, version, job.job_type)
        _fail(session, job, version, "vector_store_error", str(exc))
        return "failed"
    except Exception as exc:  # noqa: BLE001 - record anything unexpected
        _cleanup_partial_vectors(settings, version, job.job_type)
        _fail(session, job, version, type(exc).__name__, str(exc)[:2000])
        return "failed"
    job.status = "succeeded"
    job.progress = 100
    job.finished_at = utcnow()
    session.commit()
    return "succeeded"


def _fail(session: Session, job, version, code: str, detail: str) -> None:
    # A job that keeps failing goes to dead instead of failed so the retry
    # endpoint and the teacher UI can show it needs human attention.
    job.status = (
        "dead" if job.attempt_count >= get_settings().knowledge_job_max_attempts
        else "failed"
    )
    job.error_code = code[:100]
    job.error_detail = detail[:2000]
    job.finished_at = utcnow()
    if version is not None:
        version.status = "failed"
        version.error_code = code[:100]
    session.commit()


def _cleanup_partial_vectors(settings, version, job_type: str) -> None:
    """Best-effort removal of vectors from a failed ingest attempt.

    Point ids are deterministic now, so a retry overwrites them anyway, but a
    version whose chunk set shrank between attempts would leave orphans.
    """
    if job_type == "purge" or version is None:
        return
    try:
        store = get_vector_store(
            settings, version.embedding_dimensions or settings.embedding_dimensions
        )
        store.delete_by_version(version.id)
    except Exception:  # noqa: BLE001 - cleanup must never mask the real error
        pass


def _ingest_version(
    session: Session, settings, document: KnowledgeDocument, version: KnowledgeDocumentVersion
) -> None:
    if not version.storage_key:
        raise IngestionError("file_missing", "version has no stored file")
    path = storage_root(settings) / version.storage_key
    if not path.is_file():
        raise IngestionError("file_missing", f"stored file not found: {version.storage_key}")

    version.status = "parsing"
    session.commit()
    parsed = parse_file(path)

    version.status = "chunking"
    session.commit()
    chunks = build_chunks(document.document_key, document.title, parsed.sections)
    if not chunks:
        raise IngestionError("no_chunks", "parser produced no usable text")

    provider = get_embedding_provider(settings)
    version.status = "embedding"
    version.parser_name = "lightweight"
    version.parser_version = "1"
    version.embedding_model = provider.model_name
    version.embedding_dimensions = provider.dimensions
    session.commit()

    vectors = provider.embed_documents([chunk.content for chunk in chunks])

    # The collection is created at the live provider's dimensionality: a
    # degraded hash embedder (256d) must never write into a 512d collection.
    store = get_vector_store(settings, provider.dimensions)
    points = [
        UpsertPoint(
            point_id=new_point_id(version.id, chunk.chunk_index, chunk.content_sha256),
            vector=vector,
            payload={
                "organization_id": _organization_id_for_document(session, document),
                "knowledge_base_id": document.knowledge_base_id,
                "document_id": document.id,
                "document_version_id": version.id,
                "chunk_key": chunk.logical_chunk_key,
                "status": "ready",
                "section_path": chunk.section_path,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "content": chunk.content,
            },
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
    store.upsert(points)

    # Replace chunk rows only after vectors landed: an old failed attempt must
    # not leave half-written rows behind.
    session.execute(
        KnowledgeChunk.__table__.delete().where(
            KnowledgeChunk.document_version_id == version.id
        )
    )
    for chunk, point in zip(chunks, points, strict=True):
        session.add(
            KnowledgeChunk(
                id=point.point_id,
                document_version_id=version.id,
                logical_chunk_key=chunk.logical_chunk_key,
                chunk_index=chunk.chunk_index,
                section_path=chunk.section_path,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                content=chunk.content,
                content_sha256=chunk.content_sha256,
                token_count=chunk.token_count,
                qdrant_point_id=point.point_id,
            )
        )
    version.chunk_count = len(chunks)
    version.status = "ready"
    version.error_code = None
    version.published_at = utcnow()
    # Atomic switch: the document's current pointer only moves once every
    # chunk is stored and indexed, so a failure anywhere leaves the previous
    # version serving.
    document.current_version_id = version.id
    session.commit()


def _organization_id_for_document(session: Session, document: KnowledgeDocument) -> str:
    from app.models.knowledge import KnowledgeBase

    base = session.get(KnowledgeBase, document.knowledge_base_id)
    return base.organization_id if base else "org-default"


def _purge_version(session: Session, settings, version: KnowledgeDocumentVersion) -> None:
    """Physically remove one version: vectors, chunk rows and stored file."""
    store = get_vector_store(
        settings, version.embedding_dimensions or settings.embedding_dimensions
    )
    store.delete_by_version(version.id)
    session.execute(
        KnowledgeChunk.__table__.delete().where(KnowledgeChunk.document_version_id == version.id)
    )
    if version.storage_key:
        path = storage_root(settings) / version.storage_key
        if path.is_file():
            path.unlink()
    version.is_active = False
    version.status = "archived"
    session.commit()


def store_upload(
    settings, document_id: str, version_id: str, suffix: str, payload: bytes
) -> tuple[str, str]:
    """Persist an uploaded file; returns (storage_key, sha256)."""
    digest = hashlib.sha256(payload).hexdigest()
    relative = Path("originals") / document_id / f"{version_id}{suffix}"
    destination = storage_root(settings) / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    with open(destination, "wb") as handle:
        handle.write(payload)
    return relative.as_posix(), digest


def remove_version_file(settings, storage_key: str | None) -> None:
    """Delete exactly one version's stored file.

    Removing the whole document directory would destroy sibling versions that
    frozen classroom snapshots may still reference.
    """
    if not storage_key:
        return
    path = storage_root(settings) / storage_key
    if path.is_file():
        path.unlink()


def remove_document_files(settings, document_id: str) -> None:
    shutil.rmtree(storage_root(settings) / "originals" / document_id, ignore_errors=True)


def run_worker_loop(poll_seconds: float | None = None) -> None:
    """Standalone worker entry: claim and process jobs forever."""
    import time

    from app.db.session import sync_session_factory

    settings = get_settings()
    poll = poll_seconds if poll_seconds is not None else settings.knowledge_worker_poll_seconds
    while True:
        try:
            with sync_session_factory() as session:
                job = claim_next_job(
                    session,
                    worker_id=f"worker-{__import__('os').getpid()}",
                    settings=settings,
                )
                if job is None:
                    time.sleep(poll)
                    continue
                print(f"[knowledge-worker] processing job {job.id} ({job.job_type})", flush=True)
                status = process_job(job.id, session, settings)
                print(f"[knowledge-worker] job {job.id} -> {status}", flush=True)
        except KeyboardInterrupt:
            return
        except Exception as exc:  # noqa: BLE001 - a broken job must not stop the loop
            print(f"[knowledge-worker] loop error: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(poll)
