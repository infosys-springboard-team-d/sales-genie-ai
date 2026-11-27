"""Add interaction types and CRM synchronization logs.

Revision ID: 0003_milestone3_conversations_crm
Revises: 0002_milestone2_recommendations
Create Date: 2026-11-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_m3_conversations_crm"
down_revision = "0002_milestone2_recommendations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversation_summaries") as batch_op:
        batch_op.add_column(
            sa.Column(
                "interaction_type",
                sa.String(length=20),
                server_default=sa.text("'call'"),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_conversation_summaries_interaction_type",
            "interaction_type IN ('call', 'meeting')",
        )
    op.create_table(
        "crm_sync_logs",
        sa.Column("crm_sync_log_id", sa.Integer(), primary_key=True),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKey("leads.lead_id", ondelete="SET NULL"),
        ),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("record_ref", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("external_id", sa.String(length=255)),
        sa.Column("error_code", sa.String(length=80)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider IN ('salesforce', 'hubspot')",
            name="ck_crm_sync_logs_provider",
        ),
        sa.CheckConstraint(
            "entity_type IN ('contact', 'activity', 'deal_stage')",
            name="ck_crm_sync_logs_entity_type",
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="ck_crm_sync_logs_status",
        ),
    )
    op.create_index(
        "ix_crm_sync_logs_lead_created",
        "crm_sync_logs",
        ["lead_id", "created_at"],
    )
    op.create_index(
        "ix_crm_sync_logs_provider_record",
        "crm_sync_logs",
        ["provider", "entity_type", "record_ref", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_crm_sync_logs_provider_record", table_name="crm_sync_logs")
    op.drop_index("ix_crm_sync_logs_lead_created", table_name="crm_sync_logs")
    op.drop_table("crm_sync_logs")
    with op.batch_alter_table("conversation_summaries") as batch_op:
        batch_op.drop_constraint(
            "ck_conversation_summaries_interaction_type",
            type_="check",
        )
        batch_op.drop_column("interaction_type")
