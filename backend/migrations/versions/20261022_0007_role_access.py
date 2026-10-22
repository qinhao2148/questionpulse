"""Add role-bound classroom access credentials.

Revision ID: 20261022_0007
Revises: 20261020_0006
"""

import sqlalchemy as sa
from alembic import op

revision = "20261022_0007"
down_revision = "20261020_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("teacher_token_hash", sa.String(64)))
    op.add_column("sessions", sa.Column("join_code", sa.String(12)))
    op.create_index("ix_sessions_join_code", "sessions", ["join_code"], unique=True)
    op.add_column("participants", sa.Column("access_token_hash", sa.String(64)))


def downgrade() -> None:
    op.drop_column("participants", "access_token_hash")
    op.drop_index("ix_sessions_join_code", table_name="sessions")
    op.drop_column("sessions", "join_code")
    op.drop_column("sessions", "teacher_token_hash")
