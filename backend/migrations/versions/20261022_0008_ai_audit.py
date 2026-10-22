"""Add AI run and decision audit tables.

Revision ID: 20261022_0008
Revises: 20261022_0007
"""

import sqlalchemy as sa
from alembic import op

revision = "20261022_0008"
down_revision = "20261022_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("task_type", sa.String(50), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(100)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ai_runs_session_id", "ai_runs", ["session_id"])
    op.create_index("ix_ai_runs_task_type", "ai_runs", ["task_type"])
    op.create_index("ix_ai_runs_status", "ai_runs", ["status"])
    op.create_index("ix_ai_runs_input_fingerprint", "ai_runs", ["input_fingerprint"])
    op.create_table(
        "ai_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ai_run_id", sa.String(36), sa.ForeignKey("ai_runs.id"), nullable=False),
        sa.Column("question_id", sa.String(36), sa.ForeignKey("questions.id"), nullable=False),
        sa.Column("cluster_id", sa.String(36), sa.ForeignKey("clusters.id")),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("normalized_intent", sa.String(240), nullable=False),
        sa.Column("accepted_by", sa.String(40), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ai_decisions_ai_run_id", "ai_decisions", ["ai_run_id"])
    op.create_index("ix_ai_decisions_question_id", "ai_decisions", ["question_id"])
    op.create_index("ix_ai_decisions_cluster_id", "ai_decisions", ["cluster_id"])


def downgrade() -> None:
    op.drop_table("ai_decisions")
    op.drop_table("ai_runs")
