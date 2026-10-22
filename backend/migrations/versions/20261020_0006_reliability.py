"""Add integration degradation diagnostics.

Revision ID: 20261020_0006
Revises: 20261020_0005
"""

import sqlalchemy as sa
from alembic import op

revision = "20261020_0006"
down_revision = "20261020_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("integration_error", sa.String(200)))
    op.add_column("sessions", sa.Column("degraded_at", sa.DateTime()))


def downgrade() -> None:
    op.drop_column("sessions", "degraded_at")
    op.drop_column("sessions", "integration_error")
