"""Track a dedicated cursor for POLYV chat history sync.

Revision ID: 20261023_0013
Revises: 20261023_0012
"""

import sqlalchemy as sa
from alembic import op

revision = "20261023_0013"
down_revision = "20261023_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions", sa.Column("chat_synced_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("sessions", "chat_synced_at")
