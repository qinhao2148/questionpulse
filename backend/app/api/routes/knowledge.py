"""Knowledge base REST routes: library management, classroom binding and RAG
answer review. All write endpoints require the teacher portal token; the
appSecret-style knowledge is teacher-only data and never reaches the student
client except through explicitly published answers and materials."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.shared import (
    Authorization,
    Database,
    require_active_session,
    require_session,
    require_teacher,
    require_teacher_portal,
)
from app.core.config import get_settings
from app.knowledge.embeddings import embedding_status
from app.knowledge.ingestion import (
    remove_version_file,
    store_upload,
)
from app.knowledge.parser import SUPPORTED_EXTENSIONS
from app.knowledge.snapshot import (
    list_bindings,
    rebuild_snapshot,
    snapshot_documents,
)
from app.knowledge.vector_store import (
    KnowledgeVectorError,
    vector_store_error_code,
    vector_store_kind,
)
from app.knowledge.views import citation_views as _citation_views
from app.models.classroom import Question
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIngestionJob,
    RagAnswer,
    RagCitation,
    SessionKnowledgeSnapshot,
    SessionKnowledgeSnapshotItem,
)
from app.schemas.knowledge import (
    BindingReplaceRequest,
    BindingView,
    KnowledgeBaseView,
    KnowledgeDocumentVersionView,
    KnowledgeDocumentView,
    KnowledgeJobView,
    KnowledgeSearchHitView,
    KnowledgeSearchPreviewView,
    KnowledgeStatusView,
    RagAnswerActionRequest,
    RagAnswerView,
    SessionKnowledgeView,
    SnapshotDocumentView,
)

router = APIRouter()

DEFAULT_ORGANIZATION_ID = "org-default"
MAX_TAGS = 10


def _require_portal(authorization: Authorization) -> None:
    require_teacher_portal(authorization)


def _version_view(version: KnowledgeDocumentVersion) -> KnowledgeDocumentVersionView:
    return KnowledgeDocumentVersionView(
        id=version.id,
        version_number=version.version_number,
        original_file_name=version.original_file_name,
        status=version.status,
        error_code=version.error_code,
        chunk_count=version.chunk_count,
        embedding_model=version.embedding_model,
        embedding_dimensions=version.embedding_dimensions,
        file_sha256=version.file_sha256,
        is_active=version.is_active,
        created_at=version.created_at,
        published_at=version.published_at,
    )


def _document_view(
    document: KnowledgeDocument,
    versions: list[KnowledgeDocumentVersion],
) -> KnowledgeDocumentView:
    current = next((v for v in versions if v.id == document.current_version_id), None)
    return KnowledgeDocumentView(
        id=document.id,
        knowledge_base_id=document.knowledge_base_id,
        document_key=document.document_key,
        title=document.title,
        description=document.description,
        status=document.status,
        tags=list(document.tags_json or []),
        owner_session_id=document.owner_session_id,
        current_version=_version_view(current) if current else None,
        versions=[_version_view(version) for version in versions],
        created_at=document.created_at,
    )


async def _load_documents(
    db: AsyncSession, knowledge_base_id: str
) -> list[KnowledgeDocumentView]:
    documents = list(
        await db.scalars(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.knowledge_base_id == knowledge_base_id)
            .order_by(KnowledgeDocument.created_at)
        )
    )
    if not documents:
        return []
    versions = list(
        await db.scalars(
            select(KnowledgeDocumentVersion)
            .where(
                KnowledgeDocumentVersion.document_id.in_([d.id for d in documents])
            )
            .order_by(KnowledgeDocumentVersion.version_number)
        )
    )
    by_document: dict[str, list[KnowledgeDocumentVersion]] = {}
    for version in versions:
        by_document.setdefault(version.document_id, []).append(version)
    return [
        _document_view(document, by_document.get(document.id, []))
        for document in documents
    ]


def _run_job_in_background(job_id: str) -> None:
    """Inline ingestion attempt so a demo works without the standalone worker.

    The claim is a CAS on the queued row: when the standalone worker already
    picked the job up, this no-ops. Starlette runs sync background tasks in a
    worker thread, so the blocking parse/embed work never stalls the loop.
    """
    from app.db.session import sync_session_factory
    from app.knowledge.ingestion import claim_job, process_job

    with sync_session_factory() as session:
        if claim_job(session, job_id, worker_id="api-inline"):
            process_job(job_id, session)


@router.get("/knowledge/status")
async def knowledge_status() -> KnowledgeStatusView:
    settings = get_settings()
    embed = embedding_status(settings)
    # Force construction so the reported store kind reflects a real connection
    # attempt instead of the "not yet initialized" default.
    from app.knowledge.vector_store import get_vector_store

    try:
        get_vector_store(settings, embed.dimensions)
        store_status = "healthy" if not embed.degraded else "degraded"
        store_error = None
    except KnowledgeVectorError:
        store_status = "unavailable"
        store_error = vector_store_error_code() or "qdrant_unavailable"
    return KnowledgeStatusView(
        status=store_status,
        error_code=store_error,
        embedding={
            "provider": embed.provider,
            "model_name": embed.model_name,
            "dimensions": embed.dimensions,
            "degraded": embed.degraded,
        },
        vector_store=vector_store_kind(),
    )


@router.get("/knowledge-bases")
async def list_knowledge_bases(
    db: Database,
    authorization: Authorization = None,
) -> dict:
    _require_portal(authorization)
    bases = list(
        await db.scalars(
            select(KnowledgeBase)
            .where(KnowledgeBase.status == "active")
            .order_by(KnowledgeBase.created_at)
        )
    )
    counts: dict[str, int] = {}
    if bases:
        rows = await db.execute(
            select(KnowledgeDocument.knowledge_base_id, func.count())
            .where(
                KnowledgeDocument.knowledge_base_id.in_([b.id for b in bases]),
                KnowledgeDocument.status == "active",
                KnowledgeDocument.owner_session_id.is_(None),
            )
            .group_by(KnowledgeDocument.knowledge_base_id)
        )
        counts = {row[0]: row[1] for row in rows.all()}
    return {
        "data": [
            KnowledgeBaseView(
                id=base.id,
                name=base.name,
                description=base.description,
                visibility=base.visibility,
                status=base.status,
                document_count=counts.get(base.id, 0),
                created_at=base.created_at,
            )
            for base in bases
        ]
    }


@router.post("/knowledge-bases", status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    payload: dict, db: Database,
    authorization: Authorization = None,
) -> dict:
    _require_portal(authorization)
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="name_required")
    base = KnowledgeBase(
        organization_id=DEFAULT_ORGANIZATION_ID,
        name=name[:200],
        description=(payload.get("description") or "")[:500] or None,
        visibility=payload.get("visibility") or "company",
        created_by="teacher",
    )
    db.add(base)
    await db.commit()
    # created_at uses a server_default: refresh before touching it, or the
    # lazy load would fire outside the async greenlet context.
    await db.refresh(base)
    return {
        "data": KnowledgeBaseView(
            id=base.id,
            name=base.name,
            description=base.description,
            visibility=base.visibility,
            status=base.status,
            document_count=0,
            created_at=base.created_at,
        )
    }


@router.post("/knowledge-bases/{base_id}/archive")
async def archive_knowledge_base(
    base_id: str, db: Database,
    authorization: Authorization = None,
) -> dict:
    _require_portal(authorization)
    base = await db.get(KnowledgeBase, base_id)
    if base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="knowledge_base_not_found")
    base.status = "archived"
    await db.commit()
    return {"data": {"id": base.id, "status": base.status}}


@router.get("/knowledge-bases/{base_id}/documents")
async def list_documents(
    base_id: str, db: Database,
    authorization: Authorization = None,
) -> dict:
    _require_portal(authorization)
    base = await db.get(KnowledgeBase, base_id)
    if base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="knowledge_base_not_found")
    return {"data": await _load_documents(db, base_id)}


def _validate_upload_file(file: UploadFile, settings) -> str:
    name = file.filename or ""
    suffix = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"unsupported_format:{suffix or 'unknown'}",
        )
    declared = getattr(file, "size", None)
    if declared is not None and declared > settings.knowledge_max_file_mb * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="file_too_large")
    return suffix


@router.post("/knowledge-bases/{base_id}/documents", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    base_id: str,
    background_tasks: BackgroundTasks,
    db: Database,
    authorization: Authorization = None,
    file: UploadFile = File(...),  # noqa: B008
    title: str = Form(""),  # noqa: B008
    document_key: str = Form(""),  # noqa: B008
    tags: str = Form(""),  # noqa: B008
) -> dict:
    """Create (or version) a document and queue the ingestion job."""
    _require_portal(authorization)
    settings = get_settings()
    base = await db.get(KnowledgeBase, base_id)
    if base is None or base.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="knowledge_base_not_found")
    suffix = _validate_upload_file(file, settings)
    payload = await file.read()
    if not payload:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="file_empty")
    if len(payload) > settings.knowledge_max_file_mb * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="file_too_large")

    display_title = (title or "").strip() or (file.filename or "未命名文档")[:200]
    key = (document_key or "").strip().lower().replace(" ", "-")[:120]
    tag_list = [tag.strip() for tag in tags.split(",") if tag.strip()][:MAX_TAGS] if tags else []

    document = None
    if key:
        document = (
            await db.execute(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.knowledge_base_id == base_id,
                    KnowledgeDocument.document_key == key,
                )
            )
        ).scalars().first()
    if document is None:
        document = KnowledgeDocument(
            knowledge_base_id=base_id,
            document_key=key or f"doc-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')[:-3]}",
            title=display_title,
            tags_json=tag_list or None,
            created_by="teacher",
        )
        db.add(document)
        await db.flush()
    elif document.status != "active":
        document.status = "active"
    document.title = display_title

    max_number = (
        await db.scalar(
            select(func.max(KnowledgeDocumentVersion.version_number)).where(
                KnowledgeDocumentVersion.document_id == document.id
            )
        )
        or 0
    )
    version = KnowledgeDocumentVersion(
        document_id=document.id,
        version_number=max_number + 1,
        original_file_name=(file.filename or "upload")[:255],
        mime_type=file.content_type,
        status="uploaded",
        created_by="teacher",
    )
    db.add(version)
    await db.flush()
    try:
        storage_key, digest = store_upload(
            settings, document.id, version.id, suffix, payload
        )
    except OSError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail="file_store_failed"
        ) from exc
    version.storage_key = storage_key
    version.file_sha256 = digest

    job = KnowledgeIngestionJob(document_version_id=version.id, job_type="ingest")
    db.add(job)
    await db.commit()

    background_tasks.add_task(_run_job_in_background, job.id)
    return {
        "data": {
            "document_id": document.id,
            "version_id": version.id,
            "job_id": job.id,
            "status": version.status,
        }
    }


@router.get("/knowledge-documents/{document_id}")
async def get_document(
    document_id: str, db: Database,
    authorization: Authorization = None,
) -> dict:
    _require_portal(authorization)
    document = await db.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document_not_found")
    versions = list(
        await db.scalars(
            select(KnowledgeDocumentVersion)
            .where(KnowledgeDocumentVersion.document_id == document_id)
            .order_by(KnowledgeDocumentVersion.version_number)
        )
    )
    return {"data": _document_view(document, versions)}


@router.post("/knowledge-documents/{document_id}/versions", status_code=status.HTTP_202_ACCEPTED)
async def upload_new_version(
    document_id: str,
    background_tasks: BackgroundTasks,
    db: Database,
    authorization: Authorization = None,
    file: UploadFile = File(...),  # noqa: B008
    title: str = Form(""),  # noqa: B008
) -> dict:
    """Upload a new version of an existing document; old versions stay intact."""
    _require_portal(authorization)
    settings = get_settings()
    document = await db.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document_not_found")
    suffix = _validate_upload_file(file, settings)
    payload = await file.read()
    if not payload:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="file_empty")
    if len(payload) > settings.knowledge_max_file_mb * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="file_too_large")
    if (title or "").strip():
        document.title = title.strip()[:200]

    max_number = (
        await db.scalar(
            select(func.max(KnowledgeDocumentVersion.version_number)).where(
                KnowledgeDocumentVersion.document_id == document_id
            )
        )
        or 0
    )
    version = KnowledgeDocumentVersion(
        document_id=document_id,
        version_number=max_number + 1,
        original_file_name=(file.filename or "upload")[:255],
        mime_type=file.content_type,
        status="uploaded",
        created_by="teacher",
    )
    db.add(version)
    await db.flush()
    storage_key, digest = store_upload(settings, document_id, version.id, suffix, payload)
    version.storage_key = storage_key
    version.file_sha256 = digest
    job = KnowledgeIngestionJob(document_version_id=version.id, job_type="ingest")
    db.add(job)
    await db.commit()
    background_tasks.add_task(_run_job_in_background, job.id)
    return {
        "data": {
            "document_id": document_id,
            "version_id": version.id,
            "job_id": job.id,
            "status": version.status,
        }
    }


@router.get("/knowledge/jobs/{job_id}")
async def get_job(job_id: str, db: Database, authorization: Authorization = None) -> dict:
    _require_portal(authorization)
    job = await db.get(KnowledgeIngestionJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job_not_found")
    return {
        "data": KnowledgeJobView(
            id=job.id,
            document_version_id=job.document_version_id,
            job_type=job.job_type,
            status=job.status,
            progress=job.progress,
            attempt_count=job.attempt_count,
            error_code=job.error_code,
            error_detail=job.error_detail,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )
    }


@router.post("/knowledge/jobs/{job_id}/retry")
async def retry_job(
    job_id: str, background_tasks: BackgroundTasks, db: Database,
    authorization: Authorization = None,
) -> dict:
    _require_portal(authorization)
    job = await db.get(KnowledgeIngestionJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job_not_found")
    if job.status == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="job_running")
    job.status = "queued"
    job.error_code = None
    job.error_detail = None
    job.finished_at = None
    version = (
        await db.get(KnowledgeDocumentVersion, job.document_version_id)
        if job.document_version_id
        else None
    )
    if version is not None:
        version.status = "uploaded"
        version.error_code = None
    await db.commit()
    background_tasks.add_task(_run_job_in_background, job.id)
    return {"data": {"job_id": job.id, "status": "queued"}}


@router.post("/knowledge-document-versions/{version_id}/archive")
async def archive_version(
    version_id: str, db: Database,
    authorization: Authorization = None,
) -> dict:
    """Deactivate a version and purge its vectors when nothing references it."""
    _require_portal(authorization)
    version = await db.get(KnowledgeDocumentVersion, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version_not_found")
    referenced = (
        await db.scalar(
            select(func.count())
            .select_from(SessionKnowledgeSnapshotItem)
            .where(SessionKnowledgeSnapshotItem.document_version_id == version_id)
        )
        or 0
    )
    if referenced:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="version_referenced_by_snapshots",
        )
    store = _vector_store(version.embedding_dimensions or get_settings().embedding_dimensions)
    store.delete_by_version(version_id)
    await db.execute(
        RagCitation.__table__.delete().where(RagCitation.document_version_id == version_id)
    )
    document = await db.get(KnowledgeDocument, version.document_id)
    version.is_active = False
    version.status = "archived"
    if document is not None and document.current_version_id == version_id:
        # Unset the pointer but never delete sibling versions: history that
        # other classrooms froze must stay fully retrievable.
        document.current_version_id = None
    remove_version_file(get_settings(), version.storage_key)
    await db.commit()
    return {"data": {"version_id": version_id, "status": "archived"}}


@router.post("/knowledge-document-versions/{version_id}/retry")
async def retry_document_version(
    version_id: str,
    background_tasks: BackgroundTasks,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    """Requeue ingestion for a document version.

    The teacher UI knows versions, not job ids, so the lookup happens here.
    A running job within its lease is refused; a stale-leased or dead job can
    be rescued by requeueing.
    """
    _require_portal(authorization)
    settings = get_settings()
    version = await db.get(KnowledgeDocumentVersion, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version_not_found")
    job = (
        await db.execute(
            select(KnowledgeIngestionJob)
            .where(KnowledgeIngestionJob.document_version_id == version_id)
            .order_by(KnowledgeIngestionJob.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if job is None:
        job = KnowledgeIngestionJob(document_version_id=version_id, job_type="ingest")
        db.add(job)
        await db.flush()
    elif job.status == "running":
        lease_deadline = datetime.now(UTC).replace(tzinfo=None) - timedelta(
            seconds=settings.knowledge_job_lease_seconds
        )
        if job.locked_at is not None and job.locked_at > lease_deadline:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="job_running")
    if job.status == "queued":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="job_already_queued")
    job.status = "queued"
    job.error_code = None
    job.error_detail = None
    job.finished_at = None
    version.status = "uploaded"
    version.error_code = None
    await db.commit()
    background_tasks.add_task(_run_job_in_background, job.id)
    return {"data": {"job_id": job.id, "status": "queued"}}


@router.post("/knowledge-documents/{document_id}/versions/{version_id}/activate")
async def activate_document_version(
    document_id: str,
    version_id: str,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    """Roll the document's current pointer to a chosen (ready) version.

    Gives teachers an explicit rollback path: new uploads auto-activate, but
    an earlier version can be restored without re-uploading the file.
    """
    _require_portal(authorization)
    document = await db.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document_not_found")
    version = await db.get(KnowledgeDocumentVersion, version_id)
    if version is None or version.document_id != document_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version_not_found")
    if version.status != "ready" or not version.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="version_not_ready")
    document.current_version_id = version_id
    document.status = "active"
    await db.commit()
    return {"data": {"document_id": document_id, "current_version_id": version_id}}


def _vector_store(dimensions: int):
    from app.knowledge.vector_store import get_vector_store

    return get_vector_store(get_settings(), dimensions)


@router.post("/knowledge/search-preview")
async def search_preview(payload: dict, db: Database, authorization: Authorization = None) -> dict:
    """Teacher retrieval testbed: search within selected knowledge bases."""
    _require_portal(authorization)
    query = (payload.get("query") or "").strip()
    knowledge_base_ids = payload.get("knowledge_base_ids") or []
    if not query:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="query_required")
    limit = min(int(payload.get("limit") or 8), 30)

    # Preview must reflect what a new classroom would retrieve: the current
    # version only. Searching every ready version would mix superseded
    # policies into the results.
    version_ids: list[str] = []
    if knowledge_base_ids:
        rows = await db.execute(
            select(KnowledgeDocument.current_version_id)
            .where(
                KnowledgeDocument.knowledge_base_id.in_(knowledge_base_ids),
                KnowledgeDocument.status == "active",
                KnowledgeDocument.current_version_id.is_not(None),
            )
        )
        version_ids = [row[0] for row in rows.all()]
    if not version_ids:
        return {"data": KnowledgeSearchPreviewView(query=query, results=[])}

    from app.knowledge.embeddings import get_embedding_provider
    from app.knowledge.vector_store import get_vector_store

    settings = get_settings()
    provider = get_embedding_provider(settings)
    store = get_vector_store(settings, provider.dimensions)
    hits = store.search(
        vector=provider.embed_query(query),
        document_version_ids=version_ids,
        organization_id=DEFAULT_ORGANIZATION_ID,
        limit=limit,
    )
    titles = await _titles_for_versions(db, version_ids)
    chunk_by_point = await _chunks_for_points(db, [hit.point_id for hit in hits])
    results = []
    for hit in hits:
        chunk = chunk_by_point.get(hit.point_id)
        if chunk is None or hit.score < settings.rag_min_score:
            continue
        title_info = titles.get(chunk.document_version_id, {})
        results.append(
            KnowledgeSearchHitView(
                chunk_id=chunk.id,
                document_title=title_info.get("document_title", "未知文档"),
                version_number=title_info.get("version_number", 1),
                section_path=chunk.section_path,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                score=round(hit.score, 4),
                content=chunk.content,
            )
        )
    return {"data": KnowledgeSearchPreviewView(query=query, results=results)}


async def _titles_for_versions(db: AsyncSession, version_ids: list[str]) -> dict:
    rows = await db.execute(
        select(KnowledgeDocumentVersion, KnowledgeDocument)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeDocumentVersion.document_id)
        .where(KnowledgeDocumentVersion.id.in_(version_ids))
    )
    mapping = {}
    for version, document in rows.all():
        mapping[version.id] = {
            "document_title": document.title,
            "version_number": version.version_number,
        }
    return mapping


async def _chunks_for_points(db: AsyncSession, point_ids: list[str]) -> dict:
    if not point_ids:
        return {}
    rows = await db.scalars(
        select(KnowledgeChunk).where(KnowledgeChunk.qdrant_point_id.in_(point_ids))
    )
    return {chunk.qdrant_point_id: chunk for chunk in rows}


# ---------------------------------------------------------------- classroom bindings


@router.get("/sessions/{session_id}/knowledge")
async def get_session_knowledge(
    session_id: str, db: Database,
    authorization: Authorization = None,
) -> dict:
    classroom = await require_session(db, session_id)
    require_teacher(classroom, authorization)
    bindings = await list_bindings(db, session_id)
    kb_names = {}
    if bindings:
        rows = await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id.in_([b.knowledge_base_id for b in bindings])
            )
        )
        kb_names = {base.id: base.name for base in rows.scalars().all()}
    doc_titles = {}
    doc_ids = [b.document_id for b in bindings if b.document_id]
    if doc_ids:
        rows = await db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.id.in_(doc_ids))
        )
        doc_titles = {doc.id: doc.title for doc in rows.scalars().all()}
    snapshot_row = (
        await db.execute(
            select(SessionKnowledgeSnapshot)
            .where(SessionKnowledgeSnapshot.session_id == session_id)
            .order_by(SessionKnowledgeSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    documents = await snapshot_documents(db, snapshot_row)
    return {
        "data": SessionKnowledgeView(
            bindings=[
                BindingView(
                    id=binding.id,
                    knowledge_base_id=binding.knowledge_base_id,
                    knowledge_base_name=kb_names.get(binding.knowledge_base_id),
                    document_id=binding.document_id,
                    document_title=(
                        doc_titles.get(binding.document_id) if binding.document_id else None
                    ),
                    binding_scope=binding.binding_scope,
                    follow_latest=binding.follow_latest,
                )
                for binding in bindings
            ],
            snapshot_documents=[
                SnapshotDocumentView(
                    document_id=doc["document_id"],
                    document_title=doc["document_title"],
                    document_key=doc["document_key"],
                    document_version_id=doc["document_version_id"],
                    version_number=doc["version_number"],
                    status=doc["status"],
                    chunk_count=doc["chunk_count"],
                    embedding_model=doc["embedding_model"],
                    published_at=doc["published_at"],
                )
                for doc in documents
            ],
            frozen_at=snapshot_row.frozen_at if snapshot_row else None,
        )
    }


@router.put("/sessions/{session_id}/knowledge/bindings")
async def replace_bindings(
    session_id: str,
    payload: BindingReplaceRequest,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    classroom = await require_active_session(db, session_id)
    require_teacher(classroom, authorization)
    snapshot_row = (
        await db.execute(
            select(SessionKnowledgeSnapshot)
            .where(SessionKnowledgeSnapshot.session_id == session_id)
            .order_by(SessionKnowledgeSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if snapshot_row is not None and snapshot_row.frozen_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="knowledge_snapshot_frozen",
        )
    if len(payload.bindings) > 20:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="too_many_bindings")
    for binding in payload.bindings:
        base = await db.get(KnowledgeBase, binding.knowledge_base_id)
        if base is None or base.status != "active":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail="knowledge_base_not_found"
            )
        if binding.binding_scope == "single_document":
            if not binding.document_id:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, detail="document_id_required"
                )
            document = await db.get(KnowledgeDocument, binding.document_id)
            if document is None or document.knowledge_base_id != binding.knowledge_base_id:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, detail="document_not_in_base"
                )
        elif binding.binding_scope != "whole_knowledge_base":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_binding_scope"
            )
    from app.models.knowledge import SessionKnowledgeBinding

    await db.execute(
        SessionKnowledgeBinding.__table__.delete().where(
            SessionKnowledgeBinding.session_id == session_id
        )
    )
    seen_pairs: set[tuple[str, str | None]] = set()
    for binding in payload.bindings:
        pair = (binding.knowledge_base_id, binding.document_id)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        db.add(
            SessionKnowledgeBinding(
                session_id=session_id,
                knowledge_base_id=binding.knowledge_base_id,
                document_id=binding.document_id,
                binding_scope=binding.binding_scope,
                # follow_latest was removed from the product: a frozen
                # snapshot must never silently switch versions mid-class. The
                # column stays for schema stability but is always False.
                follow_latest=False,
            )
        )
    await db.commit()
    await rebuild_snapshot(db, session_id)
    return {"data": {"binding_count": len(seen_pairs)}}


# ---------------------------------------------------------------- rag answers


async def _rag_answer_view(
    db: AsyncSession,
    answer: RagAnswer,
    question: Question | None,
    citations: list[RagCitation],
) -> RagAnswerView:
    return RagAnswerView(
        id=answer.id,
        question_id=answer.question_id,
        cluster_id=answer.cluster_id,
        question_content=question.content if question else None,
        answer=answer.answer,
        confidence=answer.confidence,
        insufficient_evidence=answer.insufficient_evidence,
        answer_status=answer.answer_status,
        model=answer.model,
        error_code=answer.error_code,
        citations=await _citation_views(db, citations),
        created_at=answer.created_at,
    )


@router.get("/sessions/{session_id}/rag-answers")
async def list_rag_answers(
    session_id: str, db: Database, authorization: Authorization = None
) -> dict:
    classroom = await require_session(db, session_id)
    require_teacher(classroom, authorization)
    answers = list(
        await db.scalars(
            select(RagAnswer)
            .where(
                RagAnswer.session_id == session_id,
                RagAnswer.answer_status.in_(["draft", "approved", "published", "failed"]),
            )
            .order_by(RagAnswer.created_at)
        )
    )
    question_ids = [a.question_id for a in answers if a.question_id]
    questions = {}
    if question_ids:
        rows = await db.scalars(
            select(Question).where(Question.id.in_(question_ids))
        )
        questions = {q.id: q for q in rows}
    citations = list(
        await db.scalars(
            select(RagCitation)
            .where(RagCitation.rag_answer_id.in_([a.id for a in answers]))
            .order_by(RagCitation.citation_order)
        )
        if answers
        else []
    )
    citations_by_answer: dict[str, list[RagCitation]] = {}
    for citation in citations:
        citations_by_answer.setdefault(citation.rag_answer_id, []).append(citation)
    return {
        "data": [
            await _rag_answer_view(
                db,
                answer,
                questions.get(answer.question_id),
                citations_by_answer.get(answer.id, []),
            )
            for answer in answers
        ]
    }


@router.post("/sessions/{session_id}/rag-answers/{answer_id}/action")
async def act_on_rag_answer(
    session_id: str,
    answer_id: str,
    payload: RagAnswerActionRequest,
    background_tasks: BackgroundTasks,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    classroom = await require_active_session(db, session_id)
    require_teacher(classroom, authorization)
    answer = await db.get(RagAnswer, answer_id)
    if answer is None or answer.session_id != session_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="rag_answer_not_found")
    action = payload.action
    if action == "approve":
        if answer.answer_status not in ("draft",):
            raise HTTPException(status.HTTP_409_CONFLICT, detail="rag_answer_not_draft")
        answer.answer_status = "approved"
        answer.approved_by = "teacher"
        answer.approved_at = datetime.now(UTC).replace(tzinfo=None)
    elif action == "publish":
        if answer.answer_status not in ("draft", "approved"):
            raise HTTPException(status.HTTP_409_CONFLICT, detail="rag_answer_not_publishable")
        if answer.insufficient_evidence:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="rag_answer_insufficient")
        citation_count = (
            await db.scalar(
                select(func.count())
                .select_from(RagCitation)
                .where(RagCitation.rag_answer_id == answer_id)
            )
            or 0
        )
        if not citation_count:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="rag_answer_has_no_citations")
        if answer.answer_status == "draft":
            answer.approved_by = "teacher"
            answer.approved_at = datetime.now(UTC).replace(tzinfo=None)
        answer.answer_status = "published"
        answer.published_at = datetime.now(UTC).replace(tzinfo=None)
    elif action in ("reject", "dismiss"):
        if answer.answer_status == "published":
            raise HTTPException(status.HTTP_409_CONFLICT, detail="rag_answer_already_published")
        answer.answer_status = "rejected"
        # The reason becomes a knowledge-gap signal in the session report.
        answer.reject_reason = (payload.reason or "").strip()[:200] or None
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_action")
    await db.commit()
    return {"data": {"id": answer.id, "answer_status": answer.answer_status}}


@router.post("/sessions/{session_id}/questions/{question_id}/rag-answer")
async def regenerate_rag_answer(
    session_id: str,
    question_id: str,
    background_tasks: BackgroundTasks,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    classroom = await require_active_session(db, session_id)
    require_teacher(classroom, authorization)
    question = await db.get(Question, question_id)
    if question is None or question.session_id != session_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="question_not_found")
    # Mark existing drafts deleted so the background run creates a fresh one.
    existing = list(
        await db.scalars(
            select(RagAnswer).where(
                RagAnswer.question_id == question_id,
                RagAnswer.answer_status.in_(["draft", "failed"]),
            )
        )
    )
    for answer in existing:
        await db.delete(answer)
    await db.commit()
    from app.knowledge.answering import draft_answers_in_background

    background_tasks.add_task(
        draft_answers_in_background, db.bind, session_id, [question_id]
    )
    return {"data": {"question_id": question_id, "status": "queued"}}


@router.get("/sessions/{session_id}/student/knowledge-results")
async def student_knowledge_results(
    session_id: str,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    from app.api.routes.shared import resolve_student

    await require_session(db, session_id)
    await resolve_student(db, session_id, authorization)
    # Classroom-wide publication (see build_snapshot): chat-promoted questions
    # belong to shadow participants, so the asker filter would hide teacher
    # published answers from every student.
    rows = (
        await db.execute(
            select(RagAnswer, Question)
            .join(Question, Question.id == RagAnswer.question_id)
            .where(
                RagAnswer.session_id == session_id,
                RagAnswer.answer_status == "published",
            )
            .order_by(RagAnswer.published_at.desc())
            .limit(30)
        )
    ).all()
    citations = list(
        await db.scalars(
            select(RagCitation)
            .where(RagCitation.rag_answer_id.in_([row[0].id for row in rows]))
            .order_by(RagCitation.citation_order)
        )
        if rows
        else []
    )
    by_answer: dict[str, list[RagCitation]] = {}
    for citation in citations:
        by_answer.setdefault(citation.rag_answer_id, []).append(citation)
    data = []
    for answer, question in rows:
        hydrated = await _citation_views(db, by_answer.get(answer.id, []))
        data.append(
            {
                "answer_id": answer.id,
                "question_id": answer.question_id,
                "question_content": question.content,
                "answer": answer.answer,
                "published_at": answer.published_at,
                "citations": [
                    {
                        "document_title": c.document_title,
                        "version_number": c.version_number,
                        "section_path": c.section_path,
                        "page_start": c.page_start,
                        "page_end": c.page_end,
                        "location": c.location,
                    }
                    for c in hydrated
                ],
            }
        )
    return {"data": data}
