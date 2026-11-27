from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import String, cast, literal, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.crm import CrmProviderConfigurationError, CrmProviderError
from api.deps import ApiError, SessionDependency, _database_failure, logger
from api.schemas import (
    CrmSyncLogOut,
    CrmSyncOperationOut,
    CrmSyncOut,
    CrmSyncRequest,
)
from db.models import Activity, ConversationSummary, CrmSyncLog, Lead

router = APIRouter()


@router.get("/api/v1/crm/mappings")
def get_crm_mappings(request: Request) -> dict[str, dict[str, Any]]:
    mappings: dict[str, dict[str, Any]] = {}
    for provider_name, provider in request.app.state.crm_providers.items():
        mappings[provider_name] = {
            "configured": provider.is_configured(),
            "contact_object": "Lead" if provider_name == "salesforce" else "Contact",
            "activity_object": "Task",
            "lifecycle_field": (
                "Status" if provider_name == "salesforce" else "lifecyclestage"
            ),
            "lifecycle_mapping": getattr(provider, "status_mapping", {}),
            "deal_stage_field": (
                "StageName" if provider_name == "salesforce" else "dealstage"
            ),
            "deal_stage_mapping": getattr(provider, "deal_stage_mapping", {}),
            "creates_deals": False,
        }
    return mappings

def record_crm_sync(
    session: Session,
    *,
    lead_id: int,
    provider: str,
    entity_type: str,
    record_ref: str,
    status: str,
    external_id: str | None = None,
    error_code: str | None = None,
) -> CrmSyncLog:
    log_entry = CrmSyncLog(
        lead_id=lead_id,
        provider=provider,
        entity_type=entity_type,
        record_ref=record_ref,
        status=status,
        external_id=external_id,
        error_code=error_code,
    )
    session.add(log_entry)
    try:
        session.commit()
    except SQLAlchemyError as error:
        raise _database_failure(session, error) from error
    session.refresh(log_entry)
    return log_entry

@router.post(
    "/api/v1/leads/{lead_id}/crm-sync",
    response_model=CrmSyncOut,
)
def sync_lead_to_crm(
    lead_id: int,
    payload: CrmSyncRequest,
    session: SessionDependency,
    request: Request,
) -> CrmSyncOut:
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise ApiError(404, "LEAD_NOT_FOUND", "The requested lead does not exist.")
    provider: CrmSyncProvider | None = request.app.state.crm_providers.get(payload.provider)
    if provider is None:
        raise ApiError(
            503,
            "CRM_PROVIDER_NOT_CONFIGURED",
            f"The {payload.provider} CRM provider is not available.",
        )
    if not provider.is_configured():
        record_crm_sync(
            session,
            lead_id=lead_id,
            provider=payload.provider,
            entity_type="contact",
            record_ref=f"lead:{lead_id}",
            status="failed",
            error_code="CRM_NOT_CONFIGURED",
        )
        raise ApiError(
            503,
            "CRM_PROVIDER_NOT_CONFIGURED",
            f"Configure the {payload.provider} credentials before synchronizing.",
        )

    deal_stage: str | None = None
    if payload.deal_id:
        try:
            deal_stage = provider.stage_for_status(lead.lead_status)
        except CrmProviderConfigurationError as error:
            raise ApiError(503, "CRM_MAPPING_INVALID", str(error)) from error
        if not deal_stage:
            raise ApiError(
                400,
                "CRM_STAGE_MAPPING_NOT_CONFIGURED",
                "Configure a stage mapping for this lead status before updating a CRM deal.",
            )

    contact_ref = f"lead:{lead_id}"
    previous_contact_log = session.scalar(
        select(CrmSyncLog)
        .where(
            CrmSyncLog.lead_id == lead_id,
            CrmSyncLog.provider == payload.provider,
            CrmSyncLog.entity_type == "contact",
            CrmSyncLog.record_ref == contact_ref,
            CrmSyncLog.status == "succeeded",
        )
        .order_by(CrmSyncLog.created_at.desc(), CrmSyncLog.crm_sync_log_id.desc())
        .limit(1)
    )
    try:
        contact_id = provider.sync_contact(
            lead,
            previous_contact_log.external_id if previous_contact_log else None,
        )
    except CrmProviderConfigurationError as error:
        record_crm_sync(
            session,
            lead_id=lead_id,
            provider=payload.provider,
            entity_type="contact",
            record_ref=contact_ref,
            status="failed",
            error_code="CRM_MAPPING_INVALID",
        )
        raise ApiError(503, "CRM_MAPPING_INVALID", str(error)) from error
    except CrmProviderError as error:
        record_crm_sync(
            session,
            lead_id=lead_id,
            provider=payload.provider,
            entity_type="contact",
            record_ref=contact_ref,
            status="failed",
            external_id=error.external_id,
            error_code=error.code,
        )
        logger.warning(
            "CRM contact sync failed (provider=%s, code=%s)",
            payload.provider,
            error.code,
        )
        raise ApiError(502, error.code, str(error)) from error
    record_crm_sync(
        session,
        lead_id=lead_id,
        provider=payload.provider,
        entity_type="contact",
        record_ref=contact_ref,
        status="succeeded",
        external_id=contact_id,
    )
    operations = [
        CrmSyncOperationOut(
            entity_type="contact",
            status="succeeded",
            external_id=contact_id,
        )
    ]

    activities_synced = 0
    activities_failed = 0
    if payload.include_activities:
        activity_ref_expression = literal("activity:") + cast(
            Activity.activity_id, String
        )
        activity_synced_before = (
            select(CrmSyncLog.crm_sync_log_id)
            .where(
                CrmSyncLog.provider == payload.provider,
                CrmSyncLog.entity_type == "activity",
                CrmSyncLog.record_ref == activity_ref_expression,
                CrmSyncLog.status == "succeeded",
            )
            .exists()
        )
        activities = session.scalars(
            select(Activity)
            .where(
                Activity.lead_id == lead_id,
                ~activity_synced_before,
            )
            .order_by(Activity.occurred_at.desc(), Activity.activity_id.desc())
            .limit(100)
        ).all()
        conversation_ref_expression = literal("conversation:") + cast(
            ConversationSummary.summary_id, String
        )
        conversation_synced_before = (
            select(CrmSyncLog.crm_sync_log_id)
            .where(
                CrmSyncLog.provider == payload.provider,
                CrmSyncLog.entity_type == "activity",
                CrmSyncLog.record_ref == conversation_ref_expression,
                CrmSyncLog.status == "succeeded",
            )
            .exists()
        )
        summaries = session.scalars(
            select(ConversationSummary)
            .where(
                ConversationSummary.lead_id == lead_id,
                ~conversation_synced_before,
            )
            .order_by(
                ConversationSummary.created_at.desc(),
                ConversationSummary.summary_id.desc(),
            )
            .limit(100)
        ).all()
        sync_items: list[tuple[str, Activity]] = [
            (f"activity:{activity.activity_id}", activity)
            for activity in activities
        ]
        for summary in summaries:
            note_sections = [summary.summary]
            if summary.key_points:
                note_sections.append("Key points: " + "; ".join(summary.key_points))
            if summary.action_items:
                note_sections.append(
                    "Action items: " + "; ".join(summary.action_items)
                )
            sync_items.append(
                (
                    f"conversation:{summary.summary_id}",
                    Activity(
                        activity_type=summary.interaction_type,
                        details={"note": "\n".join(note_sections)},
                        occurred_at=summary.created_at,
                    ),
                )
            )
        sync_items.sort(
            key=lambda item: (item[1].occurred_at, item[0]), reverse=True
        )
        sync_items = sync_items[:100]
        sync_items.reverse()
        for activity_ref, activity in sync_items:
            previous_activity_log = session.scalar(
                select(CrmSyncLog)
                .where(
                    CrmSyncLog.provider == payload.provider,
                    CrmSyncLog.entity_type == "activity",
                    CrmSyncLog.record_ref == activity_ref,
                )
                .order_by(
                    CrmSyncLog.created_at.desc(),
                    CrmSyncLog.crm_sync_log_id.desc(),
                )
                .limit(1)
            )
            if (
                previous_activity_log is not None
                and previous_activity_log.status == "succeeded"
            ):
                continue
            try:
                activity_external_id = provider.sync_activity(
                    contact_id,
                    activity,
                    (
                        previous_activity_log.external_id
                        if previous_activity_log
                        else None
                    ),
                )
            except CrmProviderConfigurationError as error:
                code = "CRM_MAPPING_INVALID"
                activities_failed += 1
                record_crm_sync(
                    session,
                    lead_id=lead_id,
                    provider=payload.provider,
                    entity_type="activity",
                    record_ref=activity_ref,
                    status="failed",
                    error_code=code,
                )
                operations.append(
                    CrmSyncOperationOut(
                        entity_type="activity",
                        status="failed",
                        error_code=code,
                    )
                )
                logger.warning(
                    "CRM activity sync failed (provider=%s, code=%s)",
                    payload.provider,
                    code,
                )
                continue
            except CrmProviderError as error:
                activities_failed += 1
                record_crm_sync(
                    session,
                    lead_id=lead_id,
                    provider=payload.provider,
                    entity_type="activity",
                    record_ref=activity_ref,
                    status="failed",
                    external_id=error.external_id,
                    error_code=error.code,
                )
                operations.append(
                    CrmSyncOperationOut(
                        entity_type="activity",
                        status="failed",
                        external_id=error.external_id,
                        error_code=error.code,
                    )
                )
                logger.warning(
                    "CRM activity sync failed (provider=%s, code=%s)",
                    payload.provider,
                    error.code,
                )
                continue
            activities_synced += 1
            record_crm_sync(
                session,
                lead_id=lead_id,
                provider=payload.provider,
                entity_type="activity",
                record_ref=activity_ref,
                status="succeeded",
                external_id=activity_external_id,
            )
            operations.append(
                CrmSyncOperationOut(
                    entity_type="activity",
                    status="succeeded",
                    external_id=activity_external_id,
                )
            )

    deal_stage_status = "not_requested"
    if payload.deal_id and deal_stage:
        deal_ref = f"deal:{payload.deal_id}:status:{lead.lead_status}"
        previous_deal_log = session.scalar(
            select(CrmSyncLog)
            .where(
                CrmSyncLog.provider == payload.provider,
                CrmSyncLog.entity_type == "deal_stage",
                CrmSyncLog.record_ref == deal_ref,
                CrmSyncLog.status == "succeeded",
            )
            .order_by(CrmSyncLog.created_at.desc(), CrmSyncLog.crm_sync_log_id.desc())
            .limit(1)
        )
        if previous_deal_log is not None:
            deal_stage_status = "succeeded"
            operations.append(
                CrmSyncOperationOut(
                    entity_type="deal_stage",
                    status="succeeded",
                    external_id=payload.deal_id,
                )
            )
        else:
            try:
                deal_external_id = provider.sync_deal_stage(
                    payload.deal_id, deal_stage
                )
            except CrmProviderConfigurationError as error:
                code = "CRM_MAPPING_INVALID"
                deal_stage_status = "failed"
                record_crm_sync(
                    session,
                    lead_id=lead_id,
                    provider=payload.provider,
                    entity_type="deal_stage",
                    record_ref=deal_ref,
                    status="failed",
                    error_code=code,
                )
                operations.append(
                    CrmSyncOperationOut(
                        entity_type="deal_stage",
                        status="failed",
                        error_code=code,
                    )
                )
                logger.warning(
                    "CRM deal stage sync failed (provider=%s, code=%s)",
                    payload.provider,
                    code,
                )
            except CrmProviderError as error:
                deal_stage_status = "failed"
                record_crm_sync(
                    session,
                    lead_id=lead_id,
                    provider=payload.provider,
                    entity_type="deal_stage",
                    record_ref=deal_ref,
                    status="failed",
                    external_id=error.external_id,
                    error_code=error.code,
                )
                operations.append(
                    CrmSyncOperationOut(
                        entity_type="deal_stage",
                        status="failed",
                        external_id=error.external_id,
                        error_code=error.code,
                    )
                )
                logger.warning(
                    "CRM deal stage sync failed (provider=%s, code=%s)",
                    payload.provider,
                    error.code,
                )
            else:
                deal_stage_status = "succeeded"
                record_crm_sync(
                    session,
                    lead_id=lead_id,
                    provider=payload.provider,
                    entity_type="deal_stage",
                    record_ref=deal_ref,
                    status="succeeded",
                    external_id=deal_external_id,
                )
                operations.append(
                    CrmSyncOperationOut(
                        entity_type="deal_stage",
                        status="succeeded",
                        external_id=deal_external_id,
                    )
                )

    has_failures = activities_failed > 0 or deal_stage_status == "failed"
    return CrmSyncOut(
        provider=payload.provider,
        status="partial" if has_failures else "succeeded",
        contact_external_id=contact_id,
        activities_synced=activities_synced,
        activities_failed=activities_failed,
        deal_stage_status=deal_stage_status,
        operations=operations,
    )

@router.get(
    "/api/v1/leads/{lead_id}/crm-sync-logs",
    response_model=list[CrmSyncLogOut],
)
def list_crm_sync_logs(
    lead_id: int, session: SessionDependency
) -> list[CrmSyncLogOut]:
    if session.get(Lead, lead_id) is None:
        raise ApiError(404, "LEAD_NOT_FOUND", "The requested lead does not exist.")
    logs = session.scalars(
        select(CrmSyncLog)
        .where(CrmSyncLog.lead_id == lead_id)
        .order_by(CrmSyncLog.created_at.desc(), CrmSyncLog.crm_sync_log_id.desc())
        .limit(100)
    ).all()
    return [CrmSyncLogOut.model_validate(log_entry) for log_entry in logs]
