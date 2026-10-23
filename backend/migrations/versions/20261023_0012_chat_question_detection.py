"""Add POLYV chat ingestion and question classification.

Revision ID: 20261023_0012
Revises: 20261023_0011
"""

import sqlalchemy as sa
from alembic import op

revision = "20261023_0012"
down_revision = "20261023_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column(
            "participant_id", sa.String(36), sa.ForeignKey("participants.id"), nullable=True
        ),
        sa.Column("source", sa.String(32), nullable=False, server_default="polyv_chat"),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("polyv_session_id", sa.String(100), nullable=True),
        sa.Column("content", sa.String(500), nullable=False),
        sa.Column("normalized_content", sa.String(500), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("ingestion_method", sa.String(32), nullable=False, server_default="sdk"),
        sa.Column("official_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "classification_status", sa.String(32), nullable=False, server_default="pending"
        ),
        sa.Column(
            "promoted_question_id", sa.String(36), sa.ForeignKey("questions.id"), nullable=True
        ),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", "source", "external_id"),
    )
    for column in ("session_id", "participant_id", "polyv_session_id", "classification_status"):
        op.create_index(f"ix_chat_messages_{column}", "chat_messages", [column])

    op.create_table(
        "chat_classifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "chat_message_id",
            sa.String(36),
            sa.ForeignKey("chat_messages.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("ai_run_id", sa.String(36), sa.ForeignKey("ai_runs.id"), nullable=True),
        sa.Column("is_question", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("question_type", sa.String(40), nullable=False),
        sa.Column("normalized_intent", sa.String(240), nullable=False),
        sa.Column("suggested_question", sa.String(500), nullable=True),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("decision", sa.String(40), nullable=False),
        sa.Column("decided_by", sa.String(40), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_chat_classifications_chat_message_id",
        "chat_classifications",
        ["chat_message_id"],
        unique=True,
    )
    op.create_index(
        "ix_chat_classifications_ai_run_id", "chat_classifications", ["ai_run_id"]
    )


def downgrade() -> None:
    op.drop_table("chat_classifications")
    op.drop_table("chat_messages")
