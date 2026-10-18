"""Create the initial eight-table SalesGenie schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-16
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("lead_id", sa.Integer(), primary_key=True),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("industry", sa.String(length=120)),
        sa.Column("contact_name", sa.String(length=255)),
        sa.Column("email", sa.String(length=320)),
        sa.Column("phone", sa.String(length=64)),
        sa.Column("lead_status", sa.String(length=20), server_default=sa.text("'New'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "lead_status IN ('New', 'Contacted', 'Qualified', 'Proposal', 'Won', 'Lost')",
            name="ck_leads_status",
        ),
    )
    op.create_index(
        "uq_leads_email_normalized",
        "leads",
        [sa.text("lower(trim(email))")],
        unique=True,
        sqlite_where=sa.text("email IS NOT NULL AND trim(email) <> ''"),
        postgresql_where=sa.text("email IS NOT NULL AND trim(email) <> ''"),
    )
    op.create_index(
        "uq_leads_company_contact_without_email",
        "leads",
        [sa.text("lower(trim(company_name))"), sa.text("lower(trim(contact_name))")],
        unique=True,
        sqlite_where=sa.text(
            "email IS NULL AND contact_name IS NOT NULL AND trim(contact_name) <> ''"
        ),
        postgresql_where=sa.text(
            "email IS NULL AND contact_name IS NOT NULL AND trim(contact_name) <> ''"
        ),
    )
    op.create_index("ix_leads_status_created", "leads", ["lead_status", "created_at"])

    op.create_table(
        "company_insights",
        sa.Column("analysis_id", sa.Integer(), primary_key=True),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKey("leads.lead_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("potential_needs", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("opportunities", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("qualification_score", sa.Integer()),
        sa.Column("qualification_rationale", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "qualification_score IS NULL OR "
            "(qualification_score >= 0 AND qualification_score <= 100)",
            name="ck_company_insights_score_range",
        ),
    )
    op.create_index(
        "ix_company_insights_lead_created", "company_insights", ["lead_id", "created_at"]
    )

    op.create_table(
        "lead_scores",
        sa.Column("score_id", sa.Integer(), primary_key=True),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKey("leads.lead_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("factors", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("score >= 0 AND score <= 100", name="ck_lead_scores_range"),
    )
    op.create_index("ix_lead_scores_lead_created", "lead_scores", ["lead_id", "created_at"])

    op.create_table(
        "outreach_drafts",
        sa.Column("draft_id", sa.Integer(), primary_key=True),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKey("leads.lead_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("draft_type", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("draft_type IN ('email', 'message')", name="ck_outreach_drafts_type"),
    )
    op.create_index(
        "ix_outreach_drafts_lead_created", "outreach_drafts", ["lead_id", "created_at"]
    )

    op.create_table(
        "activities",
        sa.Column("activity_id", sa.Integer(), primary_key=True),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKey("leads.lead_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("activity_type", sa.String(length=60), nullable=False),
        sa.Column("details", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_activities_lead_occurred", "activities", ["lead_id", "occurred_at"])

    op.create_table(
        "conversation_summaries",
        sa.Column("summary_id", sa.Integer(), primary_key=True),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKey("leads.lead_id", ondelete="SET NULL"),
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("key_points", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("action_items", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_conversation_summaries_lead_created",
        "conversation_summaries",
        ["lead_id", "created_at"],
    )

    op.create_table(
        "import_batches",
        sa.Column("import_batch_id", sa.Integer(), primary_key=True),
        sa.Column("filename", sa.String(length=255)),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'processing'"), nullable=False),
        sa.Column("created_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("rejected_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("row_errors", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="ck_import_batches_status",
        ),
        sa.CheckConstraint(
            "created_count >= 0 AND duplicate_count >= 0 AND rejected_count >= 0",
            name="ck_import_batches_counts_nonnegative",
        ),
    )
    op.create_index("ix_import_batches_created", "import_batches", ["created_at"])

    op.create_table(
        "agent_runs",
        sa.Column("agent_run_id", sa.Integer(), primary_key=True),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKey("leads.lead_id", ondelete="SET NULL"),
        ),
        sa.Column("workflow_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("trigger_type", sa.String(length=40)),
        sa.Column("checkpoint_ref", sa.String(length=255)),
        sa.Column("error_code", sa.String(length=80)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_agent_runs_status",
        ),
    )
    op.create_index("ix_agent_runs_lead_created", "agent_runs", ["lead_id", "created_at"])
    op.create_index("ix_agent_runs_status_created", "agent_runs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_table("agent_runs")
    op.drop_table("import_batches")
    op.drop_table("conversation_summaries")
    op.drop_table("activities")
    op.drop_table("outreach_drafts")
    op.drop_table("lead_scores")
    op.drop_table("company_insights")
    op.drop_index("ix_leads_status_created", table_name="leads")
    op.drop_index("uq_leads_company_contact_without_email", table_name="leads")
    op.drop_index("uq_leads_email_normalized", table_name="leads")
    op.drop_table("leads")
