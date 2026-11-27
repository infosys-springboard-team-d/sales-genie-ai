from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from api.deps import ApiError, SessionDependency, _database_failure, _outreach_output, logger
from api.outreach import (
    OutreachContent,
    OutreachProviderConfigurationError,
    OutreachProviderError,
)
from api.schemas import (
    OutreachDraftOut,
    OutreachDraftUpdate,
    OutreachGenerationRequest,
)
from db.models import Lead, OutreachDraft

router = APIRouter()


@router.post(
    "/api/v1/leads/{lead_id}/outreach-drafts",
    response_model=OutreachDraftOut,
    status_code=201,
)
def generate_outreach_draft(
    lead_id: int,
    payload: OutreachGenerationRequest,
    session: SessionDependency,
    request: Request,
) -> OutreachDraftOut:
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise ApiError(404, "LEAD_NOT_FOUND", "The requested lead does not exist.")
    try:
        generated: OutreachContent = request.app.state.outreach_provider.generate(lead, payload)
    except OutreachProviderConfigurationError as error:
        raise ApiError(503, "AI_PROVIDER_NOT_CONFIGURED", str(error)) from error
    except OutreachProviderError as error:
        logger.warning("Outreach provider request failed (%s)", type(error).__name__)
        raise ApiError(502, "AI_PROVIDER_ERROR", str(error)) from error
    except (ValueError, UnicodeDecodeError) as error:
        logger.warning("Outreach provider response was invalid (%s)", type(error).__name__)
        raise ApiError(
            502, "AI_PROVIDER_ERROR", "Outreach content could not be generated."
        ) from error

    content = generated.body.strip()
    if payload.draft_type == "email":
        if not generated.subject:
            raise ApiError(
                502, "AI_PROVIDER_ERROR", "Outreach email is missing a subject."
            )
        content = f"Subject: {generated.subject.strip()}\n\n{content}"
    draft = OutreachDraft(
        lead_id=lead_id,
        draft_type=payload.draft_type,
        content=content,
    )
    session.add(draft)
    try:
        session.commit()
    except SQLAlchemyError as error:
        raise _database_failure(session, error) from error
    session.refresh(draft)
    return _outreach_output(draft)

@router.get(
    "/api/v1/leads/{lead_id}/outreach-drafts",
    response_model=list[OutreachDraftOut],
)
def list_outreach_drafts(
    lead_id: int, session: SessionDependency
) -> list[OutreachDraftOut]:
    if session.get(Lead, lead_id) is None:
        raise ApiError(404, "LEAD_NOT_FOUND", "The requested lead does not exist.")
    drafts = session.scalars(
        select(OutreachDraft)
        .where(OutreachDraft.lead_id == lead_id)
        .order_by(OutreachDraft.created_at.desc(), OutreachDraft.draft_id.desc())
        .limit(100)
    ).all()
    return [_outreach_output(draft) for draft in drafts]

@router.patch(
    "/api/v1/outreach-drafts/{draft_id}",
    response_model=OutreachDraftOut,
)
def update_outreach_draft(
    draft_id: int,
    payload: OutreachDraftUpdate,
    session: SessionDependency,
) -> OutreachDraftOut:
    draft = session.get(OutreachDraft, draft_id)
    if draft is None:
        raise ApiError(404, "OUTREACH_DRAFT_NOT_FOUND", "The outreach draft does not exist.")
    draft.content = payload.content
    try:
        session.commit()
    except SQLAlchemyError as error:
        raise _database_failure(session, error) from error
    session.refresh(draft)
    return _outreach_output(draft)
