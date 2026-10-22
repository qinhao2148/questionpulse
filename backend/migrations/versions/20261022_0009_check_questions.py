"""Add teacher-approved formative check questions.

Revision ID: 20261022_0009
Revises: 20261022_0008
"""

import sqlalchemy as sa
from alembic import op

revision = "20261022_0009"
down_revision = "20261022_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "check_questions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("cluster_id", sa.String(36), sa.ForeignKey("clusters.id"), nullable=False),
        sa.Column("feedback_round", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("stem", sa.String(500), nullable=False),
        sa.Column("correct_option_key", sa.String(1), nullable=False),
        sa.Column("explanation", sa.String(1000), nullable=False),
        sa.Column("source", sa.String(40), nullable=False, server_default="deepseek"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("cluster_id", "feedback_round"),
    )
    op.create_index("ix_check_questions_session_id", "check_questions", ["session_id"])
    op.create_index("ix_check_questions_cluster_id", "check_questions", ["cluster_id"])
    op.create_index("ix_check_questions_status", "check_questions", ["status"])
    op.create_table(
        "check_options",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "check_question_id",
            sa.String(36),
            sa.ForeignKey("check_questions.id"),
            nullable=False,
        ),
        sa.Column("option_key", sa.String(1), nullable=False),
        sa.Column("content", sa.String(300), nullable=False),
        sa.UniqueConstraint("check_question_id", "option_key"),
    )
    op.create_index(
        "ix_check_options_check_question_id", "check_options", ["check_question_id"]
    )
    op.create_table(
        "check_targets",
        sa.Column(
            "check_question_id",
            sa.String(36),
            sa.ForeignKey("check_questions.id"),
            primary_key=True,
        ),
        sa.Column(
            "participant_id",
            sa.String(36),
            sa.ForeignKey("participants.id"),
            primary_key=True,
        ),
    )
    op.create_table(
        "check_responses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "check_question_id",
            sa.String(36),
            sa.ForeignKey("check_questions.id"),
            nullable=False,
        ),
        sa.Column(
            "participant_id",
            sa.String(36),
            sa.ForeignKey("participants.id"),
            nullable=False,
        ),
        sa.Column("selected_option_key", sa.String(1), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("check_question_id", "participant_id"),
    )
    op.create_index(
        "ix_check_responses_check_question_id", "check_responses", ["check_question_id"]
    )
    op.create_index("ix_check_responses_participant_id", "check_responses", ["participant_id"])


def downgrade() -> None:
    op.drop_table("check_responses")
    op.drop_table("check_targets")
    op.drop_table("check_options")
    op.drop_table("check_questions")
