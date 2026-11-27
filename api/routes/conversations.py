from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from api.conversations import (
    ConversationContent,
    ConversationProviderConfigurationError,
    ConversationProviderError,
)
from api.deps import ApiError, SessionDependency, _database_failure, logger
from api.schemas import ConversationSummaryOut, ConversationSummaryRequest
from db.models import ConversationSummary, Lead

router = APIRouter()


@router.post(
    "/api/v1/leads/{lead_id}/conversation-summaries",
    response_model=ConversationSummaryOut,
    status_code=201,
)
def summarize_conversation(
    lead_id: int,
    payload: ConversationSummaryRequest,
    session: SessionDependency,
    request: Request,
) -> ConversationSummaryOut:
    if session.get(Lead, lead_id) is None:
        raise ApiError(404, "LEAD_NOT_FOUND", "The requested lead does not exist.")
    try:
        content: ConversationContent = request.app.state.conversation_provider.summarize(
            payload.interaction_type, payload.transcript
        )
    except ConversationProviderConfigurationError as error:
        raise ApiError(503, "AI_PROVIDER_NOT_CONFIGURED", str(error)) from error
    except ConversationProviderError as error:
        logger.warning(
            "Conversation summary provider failed (%s)", type(error).__name__
        )
        raise ApiError(502, "AI_PROVIDER_ERROR", str(error)) from error
    except (ValueError, UnicodeDecodeError) as error:
        logger.warning(
            "Conversation summary response was invalid (%s)", type(error).__name__
        )
        raise ApiError(
            502, "AI_PROVIDER_ERROR", "Conversation summary could not be generated."
        ) from error

    summary = ConversationSummary(
        lead_id=lead_id,
        interaction_type=payload.interaction_type,
        summary=content.summary,
        key_points=content.key_points,
        action_items=content.action_items,
    )
    session.add(summary)
    try:
        session.commit()
    except SQLAlchemyError as error:
        raise _database_failure(session, error) from error
    session.refresh(summary)
    return ConversationSummaryOut.model_validate(summary)

@router.get(
    "/api/v1/leads/{lead_id}/conversation-summaries",
    response_model=list[ConversationSummaryOut],
)
def list_conversation_summaries(
    lead_id: int, session: SessionDependency
) -> list[ConversationSummaryOut]:
    if session.get(Lead, lead_id) is None:
        raise ApiError(404, "LEAD_NOT_FOUND", "The requested lead does not exist.")
    summaries = session.scalars(
        select(ConversationSummary)
        .where(ConversationSummary.lead_id == lead_id)
        .order_by(
            ConversationSummary.created_at.desc(),
            ConversationSummary.summary_id.desc(),
        )
        .limit(100)
    ).all()
    return [
        ConversationSummaryOut.model_validate(summary) for summary in summaries
    ]
