"""Persist next-best-action recommendations with lead scores.

Revision ID: 0002_milestone2_recommendations
Revises: 0001_initial
Create Date: 2026-10-29
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_milestone2_recommendations"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_scores",
        sa.Column(
            "recommendation",
            sa.JSON(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("lead_scores", "recommendation")
