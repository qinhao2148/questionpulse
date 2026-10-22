"""Add session lifecycle and integration status.

Revision ID: 20261020_0004
Revises: 20261020_0003
"""

import sqlalchemy as sa
from alembic import op

revision = "20261020_0004"
down_revision = "20261020_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions", sa.Column("mode", sa.String(20), nullable=False, server_default="demo")
    )
    op.add_column(
        "sessions",
        sa.Column(
            "integration_status",
            sa.String(32),
            nullable=False,
            server_default="not_configured",
        ),
    )
    op.add_column("sessions", sa.Column("ended_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "ended_at")
    op.drop_column("sessions", "integration_status")
    op.drop_column("sessions", "mode")
