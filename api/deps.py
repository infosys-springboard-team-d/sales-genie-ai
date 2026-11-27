from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.schemas import (
    AnalysisOut,
    LeadOut,
    LeadScoreOut,
    OutreachDraftOut,
)
from db.models import CompanyInsight, Lead, LeadScore, OutreachDraft

logger = logging.getLogger("salesgenie.api")
CSV_MAX_BYTES = 5 * 1024 * 1024
CSV_MAX_ROWS = 10_000
CSV_FIELDS = {"company_name", "industry", "contact_name", "email", "phone", "lead_status"}


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, str]] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []


def get_session(request: Request):
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


SessionDependency = Annotated[Session, Depends(get_session)]


def _find_duplicate(session: Session, values: dict[str, Any], exclude_id: int | None = None) -> int | None:
    email = values.get("email")
    if email:
        statement = select(Lead.lead_id).where(
            func.lower(func.trim(Lead.email)) == email.strip().lower()
        )
    else:
        company_name = values.get("company_name")
        contact_name = values.get("contact_name")
        if not company_name or not contact_name:
            return None
        statement = select(Lead.lead_id).where(
            func.lower(func.trim(Lead.company_name)) == company_name.strip().lower(),
            func.lower(func.trim(Lead.contact_name)) == contact_name.strip().lower(),
        )
    if exclude_id is not None:
        statement = statement.where(Lead.lead_id != exclude_id)
    return session.scalar(statement.limit(1))


def _company_contact_key(values: dict[str, Any]) -> tuple[str, str] | None:
    company_name = values.get("company_name")
    contact_name = values.get("contact_name")
    if not company_name or not contact_name:
        return None
    return company_name.strip().lower(), contact_name.strip().lower()


def _lead_output(lead: Lead) -> LeadOut:
    return LeadOut.model_validate(lead)


def _analysis_output(analysis: CompanyInsight, score: LeadScore) -> AnalysisOut:
    return AnalysisOut(
        analysis_id=analysis.analysis_id,
        lead_id=analysis.lead_id,
        summary=analysis.summary,
        potential_needs=analysis.potential_needs,
        opportunities=analysis.opportunities,
        qualification={
            "score": score.score,
            "rationale": score.rationale,
            "factors": score.factors,
        },
        created_at=analysis.created_at,
    )


def _lead_score_output(score: LeadScore) -> LeadScoreOut:
    if score.recommendation is None:
        raise ApiError(
            500,
            "SCORE_INCONSISTENT",
            "The saved Milestone 2 score is missing its recommendation.",
        )
    return LeadScoreOut(
        score_id=score.score_id,
        lead_id=score.lead_id,
        score=score.score,
        score_label="high" if score.score >= 70 else "moderate" if score.score >= 40 else "low",
        rationale=score.rationale,
        factors=score.factors,
        recommendation=score.recommendation,
        created_at=score.created_at,
    )


def _outreach_output(draft: OutreachDraft) -> OutreachDraftOut:
    return OutreachDraftOut.model_validate(draft)


def _database_failure(session: Session, error: SQLAlchemyError) -> ApiError:
    session.rollback()
    logger.error("Database operation failed (%s)", type(error).__name__)
    return ApiError(503, "DATABASE_UNAVAILABLE", "The database operation could not be completed.")

