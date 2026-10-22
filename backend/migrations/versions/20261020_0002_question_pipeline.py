"""Add local question and clustering pipeline.

Revision ID: 20261020_0002
Revises: 20261019_0001
"""

import sqlalchemy as sa
from alembic import op

revision = "20261020_0002"
down_revision = "20261019_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "participants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("viewer_key", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(100)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("session_id", "viewer_key"),
    )
    op.create_index("ix_participants_session_id", "participants", ["session_id"])
    op.create_table(
        "clusters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("embedding_json", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_clusters_session_id", "clusters", ["session_id"])
    op.create_table(
        "questions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column(
            "participant_id", sa.String(36), sa.ForeignKey("participants.id"), nullable=False
        ),
        sa.Column("cluster_id", sa.String(36), sa.ForeignKey("clusters.id")),
        sa.Column("content", sa.String(500), nullable=False),
        sa.Column("normalized_content", sa.String(500), nullable=False),
        sa.Column("processing_status", sa.String(32), nullable=False),
        sa.Column("assignment_method", sa.String(50)),
        sa.Column("similarity", sa.Float()),
        sa.Column("embedding_json", sa.Text()),
        sa.Column("embedding_model", sa.String(100)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    for column in ("session_id", "participant_id", "cluster_id", "processing_status"):
        op.create_index(f"ix_questions_{column}", "questions", [column])
    op.create_table(
        "submissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column(
            "participant_id", sa.String(36), sa.ForeignKey("participants.id"), nullable=False
        ),
        sa.Column("client_request_id", sa.String(80), nullable=False),
        sa.Column("question_id", sa.String(36), sa.ForeignKey("questions.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("session_id", "participant_id", "client_request_id"),
    )
    op.create_index("ix_submissions_session_id", "submissions", ["session_id"])
    op.create_table(
        "cluster_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("cluster_id", sa.String(36), sa.ForeignKey("clusters.id"), nullable=False),
        sa.Column("question_id", sa.String(36), sa.ForeignKey("questions.id")),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("is_automatic", sa.Boolean(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_cluster_events_session_id", "cluster_events", ["session_id"])


def downgrade() -> None:
    op.drop_table("cluster_events")
    op.drop_table("submissions")
    op.drop_table("questions")
    op.drop_table("clusters")
    op.drop_table("participants")
