"""Track viewer presence and allow multiple student tokens per participant.

Revision ID: 20261023_0011
Revises: 20261022_0010
"""

import sqlalchemy as sa
from alembic import op

revision = "20261023_0011"
down_revision = "20261022_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("participants", sa.Column("last_seen_at", sa.DateTime()))
    op.add_column(
        "participants",
        sa.Column("source", sa.String(length=20), nullable=False, server_default="student"),
    )
    # 历史数据里没有显示名的参与者都是直播平台同步提问时派生的影子身份。
    op.execute("UPDATE participants SET source = 'polyv' WHERE display_name IS NULL")
    op.create_table(
        "participant_tokens",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "participant_id",
            sa.String(length=36),
            sa.ForeignKey("participants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_participant_tokens_token_hash"),
    )
    op.create_index(
        "ix_participant_tokens_participant_id", "participant_tokens", ["participant_id"]
    )


def downgrade() -> None:
    # MySQL 会为外键自动维护索引，显式 drop_index 会被拒绝；drop_table 会一并清理。
    op.drop_table("participant_tokens")
    op.drop_column("participants", "source")
    op.drop_column("participants", "last_seen_at")
