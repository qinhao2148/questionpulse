"""Add cluster state and feedback loop.

Revision ID: 20261020_0003
Revises: 20261020_0002
"""

import sqlalchemy as sa
from alembic import op

revision = "20261020_0003"
down_revision = "20261020_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clusters", sa.Column("feedback_round", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("clusters", sa.Column("closed_at", sa.DateTime(), nullable=True))
    op.create_table(
        "feedback_targets",
        sa.Column("cluster_id", sa.String(36), sa.ForeignKey("clusters.id"), primary_key=True),
        sa.Column("round", sa.Integer(), primary_key=True),
        sa.Column(
            "participant_id", sa.String(36), sa.ForeignKey("participants.id"), primary_key=True
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cluster_id", sa.String(36), sa.ForeignKey("clusters.id"), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column(
            "participant_id", sa.String(36), sa.ForeignKey("participants.id"), nullable=False
        ),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("cluster_id", "round", "participant_id"),
    )
    op.create_index("ix_feedback_cluster_id", "feedback", ["cluster_id"])


def downgrade() -> None:
    op.drop_table("feedback")
    op.drop_table("feedback_targets")
    op.drop_column("clusters", "closed_at")
    op.drop_column("clusters", "feedback_round")
