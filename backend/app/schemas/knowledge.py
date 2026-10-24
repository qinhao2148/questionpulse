"""API view models for the knowledge base and RAG answers."""

from datetime import datetime

from pydantic import BaseModel, Field


class KnowledgeBaseView(BaseModel):
    id: str
    name: str
    description: str | None
    visibility: str
    status: str
    document_count: int = 0
    created_at: datetime


class KnowledgeDocumentVersionView(BaseModel):
    id: str
    version_number: int
    original_file_name: str
    status: str
    error_code: str | None
    chunk_count: int | None
    embedding_model: str | None
    embedding_dimensions: int | None
    file_sha256: str | None
    is_active: bool
    created_at: datetime
    published_at: datetime | None


class KnowledgeDocumentView(BaseModel):
    id: str
    knowledge_base_id: str
    document_key: str
    title: str
    description: str | None
    status: str
    tags: list[str] = []
    owner_session_id: str | None
    current_version: KnowledgeDocumentVersionView | None = None
    versions: list[KnowledgeDocumentVersionView] = []
    created_at: datetime


class KnowledgeJobView(BaseModel):
    id: str
    document_version_id: str | None
    job_type: str
    status: str
    progress: int
    attempt_count: int
    error_code: str | None
    error_detail: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class KnowledgeStatusView(BaseModel):
    # healthy: qdrant + real embedder; degraded: hash fallback embedder;
    # unavailable: qdrant unreachable, upload and retrieval are refused.
    status: str
    error_code: str | None = None
    embedding: dict
    vector_store: str


class KnowledgeSearchHitView(BaseModel):
    chunk_id: str
    document_title: str
    version_number: int
    section_path: str | None
    page_start: int | None
    page_end: int | None
    score: float
    content: str


class KnowledgeSearchPreviewView(BaseModel):
    query: str
    results: list[KnowledgeSearchHitView]


class BindingInput(BaseModel):
    knowledge_base_id: str
    document_id: str | None = None
    binding_scope: str = "whole_knowledge_base"
    follow_latest: bool = False


class BindingReplaceRequest(BaseModel):
    bindings: list[BindingInput] = Field(default_factory=list)


class BindingView(BaseModel):
    id: str
    knowledge_base_id: str
    knowledge_base_name: str | None = None
    document_id: str | None
    document_title: str | None = None
    binding_scope: str
    follow_latest: bool


class SnapshotDocumentView(BaseModel):
    document_id: str
    document_title: str
    document_key: str
    document_version_id: str
    version_number: int
    status: str
    chunk_count: int | None
    embedding_model: str | None
    published_at: datetime | None


class SessionKnowledgeView(BaseModel):
    bindings: list[BindingView]
    snapshot_documents: list[SnapshotDocumentView]
    frozen_at: datetime | None = None


class CitationView(BaseModel):
    chunk_id: str
    document_title: str
    version_number: int
    section_path: str | None
    page_start: int | None
    page_end: int | None
    score: float | None
    location: str
    content: str


class RagAnswerView(BaseModel):
    id: str
    question_id: str | None
    cluster_id: str | None
    question_content: str | None = None
    answer: str | None
    confidence: float | None
    insufficient_evidence: bool
    answer_status: str
    model: str | None
    error_code: str | None
    citations: list[CitationView] = []
    created_at: datetime


class RagAnswerActionRequest(BaseModel):
    action: str  # approve | reject | publish | dismiss
    # Teacher-entered reason on rejection; feeds the knowledge-gap report.
    reason: str | None = None
