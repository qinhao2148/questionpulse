"""Add expiration timestamps for classroom access tokens.

Revision ID: 20261022_0010
Revises: 20261022_0009
"""

import sqlalchemy as sa
from alembic import op

revision = "20261022_0010"
down_revision = "20261022_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("teacher_token_expires_at", sa.DateTime()))
    op.add_column("participants", sa.Column("access_token_expires_at", sa.DateTime()))


def downgrade() -> None:
    op.drop_column("participants", "access_token_expires_at")
    op.drop_column("sessions", "teacher_token_expires_at")
