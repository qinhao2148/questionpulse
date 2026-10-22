"""Add POLYV contract identifiers and source deduplication.

Revision ID: 20261020_0005
Revises: 20261020_0004
"""

import sqlalchemy as sa
from alembic import op

revision = "20261020_0005"
down_revision = "20261020_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("polyv_channel_id", sa.String(64)))
    op.add_column("sessions", sa.Column("polyv_session_id", sa.String(100)))
    op.add_column("sessions", sa.Column("last_synced_at", sa.DateTime()))
    op.create_index("ix_sessions_polyv_channel_id", "sessions", ["polyv_channel_id"])
    op.create_index("ix_sessions_polyv_session_id", "sessions", ["polyv_session_id"])
    op.add_column(
        "questions",
        sa.Column("source", sa.String(32), nullable=False, server_default="questionpulse"),
    )
    op.add_column("questions", sa.Column("external_id", sa.String(100)))
    op.add_column("questions", sa.Column("occurred_at", sa.DateTime()))
    op.create_unique_constraint(
        "uq_questions_session_source_external", "questions", ["session_id", "source", "external_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_questions_session_source_external", "questions", type_="unique")
    op.drop_column("questions", "occurred_at")
    op.drop_column("questions", "external_id")
    op.drop_column("questions", "source")
    op.drop_index("ix_sessions_polyv_session_id", table_name="sessions")
    op.drop_index("ix_sessions_polyv_channel_id", table_name="sessions")
    op.drop_column("sessions", "last_synced_at")
    op.drop_column("sessions", "polyv_session_id")
    op.drop_column("sessions", "polyv_channel_id")
