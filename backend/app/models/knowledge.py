"""Knowledge base models: long-lived documents, immutable versions, chunk index
metadata, classroom bindings and auditable RAG answers.

The knowledge base is a long-lived asset; a classroom only ever references a
frozen set of document versions (its snapshot), so later document updates never
rewrite history for classrooms that already used the old version.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

DEFAULT_ORGANIZATION_ID = "org-default"


class Organization(Base):
    """Company tenant. MVP auto-creates a single default organization row."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(500))
    visibility: Mapped[str] = mapped_column(String(20), default="company")
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )


class KnowledgeDocument(Base):
    """A logical document. File bytes live on versions, never here."""

    __tablename__ = "knowledge_documents"
    __table_args__ = (UniqueConstraint("knowledge_base_id", "document_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    knowledge_base_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    document_key: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(500))
    # Plain string, no FK: it points at the version that becomes current only
    # after a successful atomic publish, and both rows are created together.
    current_version_id: Mapped[str | None] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    tags_json: Mapped[list | None] = mapped_column(JSON)
    # Session-scoped temporary uploads (classroom handouts) set this; they are
    # not listed in the company-wide knowledge library.
    owner_session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id"), index=True)
    created_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )


class KnowledgeDocumentVersion(Base):
    """One immutable upload of a document. Never overwritten, only published."""

    __tablename__ = "knowledge_document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    original_file_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    storage_key: Mapped[str | None] = mapped_column(String(255))
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    parser_name: Mapped[str | None] = mapped_column(String(50))
    parser_version: Mapped[str | None] = mapped_column(String(20))
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer)
    # uploaded -> parsing -> chunking -> embedding -> ready / failed / archived
    status: Mapped[str] = mapped_column(String(20), default="uploaded", index=True)
    error_code: Mapped[str | None] = mapped_column(String(100))
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeChunk(Base):
    """Auditable text kept in MySQL; the vector itself lives in Qdrant."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("document_version_id", "chunk_index"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"), index=True
    )
    logical_chunk_key: Mapped[str] = mapped_column(String(300), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    section_path: Mapped[str | None] = mapped_column(String(500))
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    token_count: Mapped[int | None] = mapped_column(Integer)
    qdrant_point_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class KnowledgeIngestionJob(Base):
    """Queue row claimed by the standalone knowledge worker process."""

    __tablename__ = "knowledge_ingestion_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(30), default="ingest")
    # queued -> running -> succeeded / failed
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_by: Mapped[str | None] = mapped_column(String(100))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionKnowledgeBinding(Base):
    """Teacher-configured classroom scope: which knowledge, at which freshness."""

    __tablename__ = "session_knowledge_bindings"
    __table_args__ = (UniqueConstraint("session_id", "knowledge_base_id", "document_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    knowledge_base_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    # NULL with scope=whole_knowledge_base; a document id for single_document.
    document_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_documents.id"))
    binding_scope: Mapped[str] = mapped_column(String(30), default="whole_knowledge_base")
    # False (default) = snapshot locks the version active at binding time;
    # True = the snapshot refreshes to the latest ready version on each use.
    follow_latest: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SessionKnowledgeSnapshot(Base):
    """The resolved set of document versions a classroom actually reads."""

    __tablename__ = "session_knowledge_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    # Lazy freeze: rebuildable on binding changes until the first real RAG
    # retrieval touches it; after frozen_at is set the versions never change.
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )


class SessionKnowledgeSnapshotItem(Base):
    __tablename__ = "session_knowledge_snapshot_items"

    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("session_knowledge_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_document_versions.id"), primary_key=True
    )


class RagAnswer(Base):
    """AI-drafted answer over classroom knowledge; teacher gates publication."""

    __tablename__ = "rag_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    question_id: Mapped[str | None] = mapped_column(ForeignKey("questions.id"), index=True)
    cluster_id: Mapped[str | None] = mapped_column(ForeignKey("clusters.id"), index=True)
    answer: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    insufficient_evidence: Mapped[bool] = mapped_column(Boolean, default=False)
    # draft -> approved -> published, or rejected. Also 'failed' for errors.
    answer_status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(100))
    approved_by: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Teacher-entered reason on rejection; feeds the knowledge-gap report.
    reject_reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RagCitation(Base):
    __tablename__ = "rag_citations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    rag_answer_id: Mapped[str] = mapped_column(
        ForeignKey("rag_answers.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[str] = mapped_column(ForeignKey("knowledge_chunks.id"))
    document_version_id: Mapped[str] = mapped_column(ForeignKey("knowledge_document_versions.id"))
    citation_order: Mapped[int] = mapped_column(Integer, default=1)
    retrieval_score: Mapped[float | None] = mapped_column(Float)
    quoted_text: Mapped[str | None] = mapped_column(Text)
