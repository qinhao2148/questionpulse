"""Track teacher rejection reasons on RAG answers.

Rejected/failed/insufficient answers are knowledge-gap signals: the report
surfaces them so the teacher knows which topics need new or corrected
documents.

Revision ID: 20261024_0015
Revises: 20261024_0014
"""

import sqlalchemy as sa
from alembic import op

revision = "20261024_0015"
down_revision = "20261024_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rag_answers", sa.Column("reject_reason", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("rag_answers", "reject_reason")
