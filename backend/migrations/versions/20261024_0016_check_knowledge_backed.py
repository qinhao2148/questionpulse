"""Mark whether a check question is backed by classroom knowledge.

Quizzes generated with retrieved knowledge contexts are traceable to the
bound documents; ones generated from student questions alone (no knowledge
match) are flagged so the teacher knows the check may exceed the material.

Revision ID: 20261024_0016
Revises: 20261024_0015
"""

import sqlalchemy as sa
from alembic import op

revision = "20261024_0016"
down_revision = "20261024_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "check_questions",
        sa.Column(
            "knowledge_backed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("check_questions", "knowledge_backed")
