from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        CheckConstraint(
            "lead_status IN ('New', 'Contacted', 'Qualified', 'Proposal', 'Won', 'Lost')",
            name="ck_leads_status",
        ),
        Index(
            "uq_leads_email_normalized",
            text("lower(trim(email))"),
            unique=True,
            sqlite_where=text("email IS NOT NULL AND trim(email) <> ''"),
            postgresql_where=text("email IS NOT NULL AND trim(email) <> ''"),
        ),
        Index(
            "uq_leads_company_contact_without_email",
            text("lower(trim(company_name))"),
            text("lower(trim(contact_name))"),
            unique=True,
            sqlite_where=text(
                "email IS NULL AND contact_name IS NOT NULL AND trim(contact_name) <> ''"
            ),
            postgresql_where=text(
                "email IS NULL AND contact_name IS NOT NULL AND trim(contact_name) <> ''"
            ),
        ),
        Index("ix_leads_status_created", "lead_status", "created_at"),
    )

    lead_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(120))
    contact_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(64))
    lead_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'New'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class CompanyInsight(Base):
    __tablename__ = "company_insights"
    __table_args__ = (
        CheckConstraint(
            "qualification_score IS NULL OR "
            "(qualification_score >= 0 AND qualification_score <= 100)",
            name="ck_company_insights_score_range",
        ),
        Index("ix_company_insights_lead_created", "lead_id", "created_at"),
    )

    analysis_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.lead_id", ondelete="CASCADE"), nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    potential_needs: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    opportunities: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    qualification_score: Mapped[int | None] = mapped_column(Integer)
    qualification_rationale: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LeadScore(Base):
    __tablename__ = "lead_scores"
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 100", name="ck_lead_scores_range"),
        Index("ix_lead_scores_lead_created", "lead_id", "created_at"),
    )

    score_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.lead_id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    factors: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OutreachDraft(Base):
    __tablename__ = "outreach_drafts"
    __table_args__ = (
        CheckConstraint(
            "draft_type IN ('email', 'message')", name="ck_outreach_drafts_type"
        ),
        Index("ix_outreach_drafts_lead_created", "lead_id", "created_at"),
    )

    draft_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.lead_id", ondelete="CASCADE"), nullable=False
    )
    draft_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (Index("ix_activities_lead_occurred", "lead_id", "occurred_at"),)

    activity_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.lead_id", ondelete="CASCADE"), nullable=False
    )
    activity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"
    __table_args__ = (Index("ix_conversation_summaries_lead_created", "lead_id", "created_at"),)

    summary_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(
        ForeignKey("leads.lead_id", ondelete="SET NULL")
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_points: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    action_items: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="ck_import_batches_status",
        ),
        CheckConstraint(
            "created_count >= 0 AND duplicate_count >= 0 AND rejected_count >= 0",
            name="ck_import_batches_counts_nonnegative",
        ),
        Index("ix_import_batches_created", "created_at"),
    )

    import_batch_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'processing'")
    )
    created_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    duplicate_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    rejected_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    row_errors: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_agent_runs_status",
        ),
        Index("ix_agent_runs_lead_created", "lead_id", "created_at"),
        Index("ix_agent_runs_status_created", "status", "created_at"),
    )

    agent_run_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(
        ForeignKey("leads.lead_id", ondelete="SET NULL")
    )
    workflow_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'queued'")
    )
    trigger_type: Mapped[str | None] = mapped_column(String(40))
    checkpoint_ref: Mapped[str | None] = mapped_column(String(255))
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
