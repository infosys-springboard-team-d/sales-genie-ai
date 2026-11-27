"""Add SalesAnalytics storage and optional Lead estimated_value.

Revision ID: 0004_m4_sales_analytics
Revises: 0003_m3_conversations_crm
Create Date: 2026-11-27
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_m4_sales_analytics"
down_revision = "0003_m3_conversations_crm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("estimated_value", sa.Float(), nullable=True))

    op.create_table(
        "sales_analytics",
        sa.Column("analytics_id", sa.Integer(), primary_key=True),
        sa.Column("period", sa.String(length=20), nullable=False),
        sa.Column(
            "total_leads",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "won_leads",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "conversion_rate",
            sa.Float(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "pipeline_value",
            sa.Float(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("avg_response_time_hours", sa.Float(), nullable=True),
        sa.Column("avg_sales_cycle_days", sa.Float(), nullable=True),
        sa.Column(
            "stage_breakdown",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "follow_up_recommendations",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "period IN ('this_month', 'this_quarter', 'this_year', 'all_time')",
            name="ck_sales_analytics_period",
        ),
        sa.CheckConstraint(
            "total_leads >= 0 AND won_leads >= 0",
            name="ck_sales_analytics_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "conversion_rate >= 0 AND conversion_rate <= 100",
            name="ck_sales_analytics_conversion_range",
        ),
        sa.CheckConstraint(
            "pipeline_value >= 0",
            name="ck_sales_analytics_pipeline_nonnegative",
        ),
    )
    op.create_index(
        "ix_sales_analytics_period_computed",
        "sales_analytics",
        ["period", "computed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_sales_analytics_period_computed", table_name="sales_analytics")
    op.drop_table("sales_analytics")
    op.drop_column("leads", "estimated_value")
