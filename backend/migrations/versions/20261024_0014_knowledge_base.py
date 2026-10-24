"""Knowledge base, document versions, classroom bindings and RAG answers.

Revision ID: 20261024_0014
Revises: 20261023_0013
"""

import sqlalchemy as sa
from alembic import op

revision = "20261024_0014"
down_revision = "20261023_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.execute(
        "INSERT INTO organizations (id, name, status) "
        "VALUES ('org-default', 'Default Organization', 'active')"
    )

    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="company"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_knowledge_bases_organization_id", "knowledge_bases", ["organization_id"]
    )

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "knowledge_base_id",
            sa.String(36),
            sa.ForeignKey("knowledge_bases.id"),
            nullable=False,
        ),
        sa.Column("document_key", sa.String(120), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("current_version_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("tags_json", sa.JSON(), nullable=True),
        sa.Column("owner_session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("knowledge_base_id", "document_key", name="uq_kdoc_key"),
    )
    op.create_index(
        "ix_knowledge_documents_knowledge_base_id",
        "knowledge_documents",
        ["knowledge_base_id"],
    )
    op.create_index(
        "ix_knowledge_documents_owner_session_id",
        "knowledge_documents",
        ["owner_session_id"],
    )
    op.create_index(
        "ix_knowledge_documents_current_version_id",
        "knowledge_documents",
        ["current_version_id"],
    )

    op.create_table(
        "knowledge_document_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("knowledge_documents.id"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("original_file_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("storage_key", sa.String(255), nullable=True),
        sa.Column("file_sha256", sa.String(64), nullable=True),
        sa.Column("parser_name", sa.String(50), nullable=True),
        sa.Column("parser_version", sa.String(20), nullable=True),
        sa.Column("embedding_model", sa.String(100), nullable=True),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="uploaded"),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("document_id", "version_number", name="uq_kdocver_number"),
    )
    op.create_index(
        "ix_knowledge_document_versions_document_id",
        "knowledge_document_versions",
        ["document_id"],
    )
    op.create_index(
        "ix_knowledge_document_versions_status", "knowledge_document_versions", ["status"]
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_version_id",
            sa.String(36),
            sa.ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("logical_chunk_key", sa.String(300), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("section_path", sa.String(500), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("qdrant_point_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_version_id", "chunk_index", name="uq_kchunk_index"),
    )
    op.create_index(
        "ix_knowledge_chunks_document_version_id",
        "knowledge_chunks",
        ["document_version_id"],
    )
    op.create_index(
        "ix_knowledge_chunks_logical_chunk_key", "knowledge_chunks", ["logical_chunk_key"]
    )

    op.create_table(
        "knowledge_ingestion_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_version_id",
            sa.String(36),
            sa.ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("job_type", sa.String(30), nullable=False, server_default="ingest"),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_by", sa.String(100), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_knowledge_ingestion_jobs_document_version_id",
        "knowledge_ingestion_jobs",
        ["document_version_id"],
    )
    op.create_index(
        "ix_knowledge_ingestion_jobs_status", "knowledge_ingestion_jobs", ["status"]
    )

    op.create_table(
        "session_knowledge_bindings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column(
            "knowledge_base_id",
            sa.String(36),
            sa.ForeignKey("knowledge_bases.id"),
            nullable=False,
        ),
        sa.Column(
            "document_id", sa.String(36), sa.ForeignKey("knowledge_documents.id"), nullable=True
        ),
        sa.Column(
            "binding_scope", sa.String(30), nullable=False, server_default="whole_knowledge_base"
        ),
        sa.Column("follow_latest", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", "knowledge_base_id", "document_id", name="uq_sbind"),
    )
    op.create_index(
        "ix_session_knowledge_bindings_session_id",
        "session_knowledge_bindings",
        ["session_id"],
    )
    op.create_index(
        "ix_session_knowledge_bindings_knowledge_base_id",
        "session_knowledge_bindings",
        ["knowledge_base_id"],
    )

    op.create_table(
        "session_knowledge_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("frozen_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("refreshed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_session_knowledge_snapshots_session_id", "session_knowledge_snapshots", ["session_id"]
    )

    op.create_table(
        "session_knowledge_snapshot_items",
        sa.Column(
            "snapshot_id",
            sa.String(36),
            sa.ForeignKey("session_knowledge_snapshots.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "document_version_id",
            sa.String(36),
            sa.ForeignKey("knowledge_document_versions.id"),
            primary_key=True,
        ),
    )

    op.create_table(
        "rag_answers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("question_id", sa.String(36), sa.ForeignKey("questions.id"), nullable=True),
        sa.Column("cluster_id", sa.String(36), sa.ForeignKey("clusters.id"), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("insufficient_evidence", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("answer_status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("approved_by", sa.String(64), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_rag_answers_session_id", "rag_answers", ["session_id"]
    )
    op.create_index(
        "ix_rag_answers_question_id", "rag_answers", ["question_id"]
    )
    op.create_index(
        "ix_rag_answers_cluster_id", "rag_answers", ["cluster_id"]
    )
    op.create_index(
        "ix_rag_answers_answer_status", "rag_answers", ["answer_status"]
    )

    op.create_table(
        "rag_citations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "rag_answer_id",
            sa.String(36),
            sa.ForeignKey("rag_answers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_id", sa.String(36), sa.ForeignKey("knowledge_chunks.id"), nullable=False),
        sa.Column(
            "document_version_id",
            sa.String(36),
            sa.ForeignKey("knowledge_document_versions.id"),
            nullable=False,
        ),
        sa.Column("citation_order", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("retrieval_score", sa.Float(), nullable=True),
        sa.Column("quoted_text", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_rag_citations_rag_answer_id", "rag_citations", ["rag_answer_id"]
    )


def downgrade() -> None:
    op.drop_table("rag_citations")
    op.drop_table("rag_answers")
    op.drop_table("session_knowledge_snapshot_items")
    op.drop_table("session_knowledge_snapshots")
    op.drop_table("session_knowledge_bindings")
    op.drop_table("knowledge_ingestion_jobs")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_document_versions")
    op.drop_table("knowledge_documents")
    op.drop_table("knowledge_bases")
    op.drop_table("organizations")
