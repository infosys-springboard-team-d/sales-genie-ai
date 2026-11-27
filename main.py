from __future__ import annotations

import csv
import io
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import String, cast, func, literal, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from pydantic import ValidationError

from api.analysis import (
    AnalysisContent,
    AnalysisProvider,
    AnalysisProviderError,
    OllamaAnalysisProvider,
    ProviderConfigurationError,
)
from api.conversations import (
    ConversationContent,
    ConversationProvider,
    ConversationProviderConfigurationError,
    ConversationProviderError,
    OllamaConversationProvider,
)
from api.crm import (
    CrmProviderConfigurationError,
    CrmProviderError,
    CrmSyncProvider,
    HubSpotCrmProvider,
    SalesforceCrmProvider,
)
from api.outreach import (
    OllamaOutreachProvider,
    OutreachContent,
    OutreachProvider,
    OutreachProviderConfigurationError,
    OutreachProviderError,
)
from api.schemas import (
    ActivityCreate,
    ActivityOut,
    AnalysisOut,
    AnalysisRequest,
    ConversationSummaryOut,
    ConversationSummaryRequest,
    CrmSyncLogOut,
    CrmSyncOperationOut,
    CrmSyncOut,
    CrmSyncRequest,
    CsvLeadInput,
    ImportResult,
    LeadCreate,
    LeadOut,
    LeadPage,
    LeadPatch,
    LeadScoreOut,
    LeadStatus,
    LeadStatusUpdate,
    OutreachDraftOut,
    OutreachDraftUpdate,
    OutreachGenerationRequest,
)
from api.scoring import score_lead, score_sales_readiness
from db.database import create_database_engine
from db.models import (
    Activity,
    CompanyInsight,
    CrmSyncLog,
    ConversationSummary,
    ImportBatch,
    Lead,
    LeadScore,
    OutreachDraft,
)


load_dotenv()
logger = logging.getLogger(__name__)
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


def create_app(
    database_url: str | None = None,
    analysis_provider: AnalysisProvider | None = None,
    outreach_provider: OutreachProvider | None = None,
    engine: Engine | None = None,
    conversation_provider: ConversationProvider | None = None,
    crm_providers: dict[str, CrmSyncProvider] | None = None,
) -> FastAPI:
    owns_engine = engine is None
    database_engine = engine or create_database_engine(
        database_url or os.getenv("DATABASE_URL", "sqlite:///./salesgenie.db")
    )
    session_factory = sessionmaker(bind=database_engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if owns_engine:
            database_engine.dispose()

    app = FastAPI(
        title="SalesGenie API",
        description=(
            "SalesGenie lead management, saved company intelligence, "
            "outreach drafts, conversation summaries, CRM synchronization, "
            "and explainable lead scoring."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.session_factory = session_factory
    app.state.engine = database_engine
    app.state.analysis_provider = analysis_provider or OllamaAnalysisProvider.from_environment()
    app.state.outreach_provider = outreach_provider or OllamaOutreachProvider.from_environment()
    app.state.conversation_provider = (
        conversation_provider
        if conversation_provider is not None
        else OllamaConversationProvider.from_environment()
    )
    app.state.crm_providers = (
        crm_providers
        if crm_providers is not None
        else {
            "salesforce": SalesforceCrmProvider.from_environment(),
            "hubspot": HubSpotCrmProvider.from_environment(),
        }
    )

    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": error.details,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in item["loc"][1:]),
                "message": item["msg"],
            }
            for item in error.errors()
        ]
        status_code = (
            422
            if request.method == "POST"
            and (
                request.url.path.endswith("/analysis")
                or request.url.path.endswith("/conversation-summaries")
            )
            else 400
        )
        return JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "The request contains invalid fields.",
                    "details": details,
                }
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(
        _request: Request, error: SQLAlchemyError
    ) -> JSONResponse:
        logger.error("Database operation failed (%s)", type(error).__name__)
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "DATABASE_UNAVAILABLE",
                    "message": "The database operation could not be completed.",
                    "details": [],
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, error: Exception) -> JSONResponse:
        logger.exception("Unexpected server error: %s", error)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": str(error) or "An unexpected server error occurred.",
                    "details": [],
                }
            },
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/leads", response_model=LeadOut, status_code=201)
    def create_lead(payload: LeadCreate, session: SessionDependency) -> LeadOut:
        values = payload.model_dump()
        if _find_duplicate(session, values) is not None:
            raise ApiError(409, "DUPLICATE_LEAD", "A lead matching this duplicate rule already exists.")
        lead = Lead(**values)
        session.add(lead)
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            if _find_duplicate(session, values) is not None:
                raise ApiError(
                    409,
                    "DUPLICATE_LEAD",
                    "A lead matching this duplicate rule already exists.",
                ) from error
            raise _database_failure(session, error) from error
        except SQLAlchemyError as error:
            raise _database_failure(session, error) from error
        session.refresh(lead)
        return _lead_output(lead)

    @app.get("/api/v1/leads", response_model=LeadPage)
    def list_leads(
        session: SessionDependency,
        q: str | None = Query(default=None, max_length=200),
        status: LeadStatus | None = None,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
    ) -> LeadPage:
        conditions = []
        if status is not None:
            conditions.append(Lead.lead_status == status.value)
        if q and q.strip():
            term = q.strip().replace("!", "!!").replace("%", "!%").replace("_", "!_")
            pattern = f"%{term}%"
            conditions.append(
                or_(
                    Lead.company_name.ilike(pattern, escape="!"),
                    Lead.contact_name.ilike(pattern, escape="!"),
                    Lead.email.ilike(pattern, escape="!"),
                    Lead.industry.ilike(pattern, escape="!"),
                )
            )
        statement = select(Lead)
        count_statement = select(func.count()).select_from(Lead)
        if conditions:
            statement = statement.where(*conditions)
            count_statement = count_statement.where(*conditions)
        total = session.scalar(count_statement) or 0
        leads = session.scalars(
            statement.order_by(Lead.lead_id.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
        return LeadPage(
            items=[_lead_output(lead) for lead in leads],
            page=page,
            page_size=page_size,
            total=total,
        )

    @app.get("/api/v1/leads/{lead_id}", response_model=LeadOut)
    def get_lead(lead_id: int, session: SessionDependency) -> LeadOut:
        lead = session.get(Lead, lead_id)
        if lead is None:
            raise ApiError(404, "LEAD_NOT_FOUND", "The requested lead does not exist.")
        return _lead_output(lead)

    @app.patch("/api/v1/leads/{lead_id}", response_model=LeadOut)
    def update_lead(lead_id: int, payload: LeadPatch, session: SessionDependency) -> LeadOut:
        lead = session.get(Lead, lead_id)
        if lead is None:
            raise ApiError(404, "LEAD_NOT_FOUND", "The requested lead does not exist.")
        values = payload.model_dump(exclude_unset=True)
        if not values:
            raise ApiError(400, "VALIDATION_ERROR", "At least one editable field is required.")
        if "company_name" in values and values["company_name"] is None:
            raise ApiError(400, "VALIDATION_ERROR", "company_name cannot be blank.")
        duplicate_values = {
            "company_name": values.get("company_name", lead.company_name),
            "contact_name": values.get("contact_name", lead.contact_name),
            "email": values.get("email", lead.email),
        }
        if _find_duplicate(session, duplicate_values, exclude_id=lead_id) is not None:
            raise ApiError(409, "DUPLICATE_LEAD", "An existing lead matches the updated details.")
        for field, value in values.items():
            setattr(lead, field, value)
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            if _find_duplicate(session, duplicate_values, exclude_id=lead_id) is not None:
                raise ApiError(
                    409, "DUPLICATE_LEAD", "An existing lead matches the updated details."
                ) from error
            raise _database_failure(session, error) from error
        except SQLAlchemyError as error:
            raise _database_failure(session, error) from error
        session.refresh(lead)
        return _lead_output(lead)

    @app.patch("/api/v1/leads/{lead_id}/status", response_model=LeadOut)
    def update_lead_status(
        lead_id: int, payload: LeadStatusUpdate, session: SessionDependency
    ) -> LeadOut:
        lead = session.get(Lead, lead_id)
        if lead is None:
            raise ApiError(404, "LEAD_NOT_FOUND", "The requested lead does not exist.")
        lead.lead_status = payload.lead_status.value
        try:
            session.commit()
        except SQLAlchemyError as error:
            raise _database_failure(session, error) from error
        session.refresh(lead)
        return _lead_output(lead)

    @app.post("/api/v1/leads/import", response_model=ImportResult)
    def import_leads(session: SessionDependency, file: UploadFile = File(...)) -> ImportResult:
        if not file.filename or not file.filename.lower().endswith(".csv"):
            raise ApiError(400, "INVALID_CSV", "Upload a file with a .csv extension.")
        content = file.file.read(CSV_MAX_BYTES + 1)
        if len(content) > CSV_MAX_BYTES:
            raise ApiError(413, "FILE_TOO_LARGE", "CSV uploads are limited to 5 MiB.")
        try:
            decoded = content.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(decoded, newline=""), strict=True)
            headers = reader.fieldnames
            if not headers or len(set(headers)) != len(headers):
                raise ApiError(400, "INVALID_CSV", "CSV headers must be present and unique.")
            unknown_headers = set(headers) - CSV_FIELDS
            if unknown_headers:
                raise ApiError(
                    400,
                    "INVALID_CSV",
                    "CSV contains unsupported columns.",
                    [{"field": "headers", "message": ", ".join(sorted(unknown_headers))}],
                )
            if "company_name" not in headers:
                raise ApiError(400, "INVALID_CSV", "CSV must include a company_name column.")
            rows = list(reader)
        except UnicodeDecodeError as error:
            raise ApiError(400, "INVALID_CSV", "CSV must use UTF-8 encoding.") from error
        except csv.Error as error:
            raise ApiError(400, "INVALID_CSV", "CSV could not be parsed.") from error
        if len(rows) > CSV_MAX_ROWS:
            raise ApiError(413, "TOO_MANY_ROWS", "CSV uploads are limited to 10,000 data rows.")

        candidates: list[tuple[int, dict[str, Any]]] = []
        duplicates = 0
        rejected = 0
        row_errors: list[dict[str, Any]] = []
        duplicate_rows: list[int] = []
        seen_emails: set[str] = set()
        seen_company_contacts: set[tuple[str, str]] = set()
        nonblank_rows = 0
        for row_number, row in enumerate(rows, start=2):
            if row is None or not any(
                value and value.strip() for value in row.values() if isinstance(value, str)
            ):
                continue
            nonblank_rows += 1
            if None in row:
                rejected += 1
                row_errors.append(
                    {
                        "row": row_number,
                        "code": "VALIDATION_ERROR",
                        "message": "Row has more values than the header.",
                    }
                )
                continue
            values = {key: value for key, value in row.items() if key in CSV_FIELDS}
            try:
                lead_data = CsvLeadInput.model_validate(values).model_dump()
            except ValidationError as error:
                rejected += 1
                messages = "; ".join(item["msg"] for item in error.errors())
                row_errors.append(
                    {"row": row_number, "code": "VALIDATION_ERROR", "message": messages}
                )
                continue
            email = lead_data.get("email")
            company_contact_key = _company_contact_key(lead_data)
            seen_duplicate = (
                email.strip().lower() in seen_emails
                if email
                else company_contact_key is not None
                and company_contact_key in seen_company_contacts
            )
            if _find_duplicate(session, lead_data) is not None or seen_duplicate:
                duplicates += 1
                duplicate_rows.append(row_number)
                row_errors.append(
                    {
                        "row": row_number,
                        "code": "DUPLICATE_LEAD",
                        "message": "A matching lead already exists in the database or this file.",
                    }
                )
                continue
            candidates.append((row_number, lead_data))
            if email:
                seen_emails.add(email.strip().lower())
            if company_contact_key is not None:
                seen_company_contacts.add(company_contact_key)

        has_errors = bool(duplicates or rejected)
        created = 0 if has_errors else len(candidates)
        rolled_back_rows = [row_number for row_number, _ in candidates] if has_errors else []
        batch = ImportBatch(
            filename=file.filename[:255],
            status="failed" if has_errors else "completed",
            created_count=created,
            duplicate_count=duplicates,
            rejected_count=rejected,
            row_errors=row_errors,
            completed_at=datetime.now(timezone.utc),
        )
        if created:
            session.add_all([Lead(**lead_data) for _, lead_data in candidates])
        session.add(batch)
        try:
            session.commit()
        except IntegrityError as error:
            raise _database_failure(session, error) from error
        except SQLAlchemyError as error:
            raise _database_failure(session, error) from error
        return ImportResult(
            created=created,
            duplicates=duplicates,
            rejected=rejected,
            committed=not has_errors,
            row_errors=row_errors,
            duplicate_rows=duplicate_rows,
            rolled_back_rows=rolled_back_rows,
        )

    @app.post(
        "/api/v1/leads/{lead_id}/analysis",
        response_model=AnalysisOut,
        status_code=201,
    )
    def analyze_lead(
        lead_id: int, payload: AnalysisRequest, session: SessionDependency
    ) -> AnalysisOut:
        lead = session.get(Lead, lead_id)
        if lead is None:
            raise ApiError(404, "LEAD_NOT_FOUND", "The requested lead does not exist.")
        try:
            content: AnalysisContent = app.state.analysis_provider.analyze(lead, payload.context)
        except ProviderConfigurationError as error:
            raise ApiError(503, "AI_PROVIDER_NOT_CONFIGURED", str(error)) from error
        except AnalysisProviderError as error:
            logger.warning("AI provider request failed (%s)", type(error).__name__)
            raise ApiError(502, "AI_PROVIDER_ERROR", str(error)) from error
        except (ValueError, UnicodeDecodeError) as error:
            logger.warning("AI provider response was invalid (%s)", type(error).__name__)
            raise ApiError(502, "AI_PROVIDER_ERROR", "Company analysis could not be generated.") from error

        score, rationale, factors = score_lead(
            lead, content.summary, content.potential_needs, content.opportunities
        )
        analysis = CompanyInsight(
            lead_id=lead_id,
            summary=content.summary,
            potential_needs=content.potential_needs,
            opportunities=content.opportunities,
            qualification_score=score,
            qualification_rationale=rationale,
        )
        lead_score = LeadScore(
            lead_id=lead_id,
            score=score,
            rationale=rationale,
            factors=factors,
        )
        session.add_all([analysis, lead_score])
        try:
            session.commit()
        except SQLAlchemyError as error:
            raise _database_failure(session, error) from error
        session.refresh(analysis)
        session.refresh(lead_score)
        return _analysis_output(analysis, lead_score)

    @app.get("/api/v1/leads/{lead_id}/analysis", response_model=AnalysisOut)
    def get_latest_analysis(lead_id: int, session: SessionDependency) -> AnalysisOut:
        if session.get(Lead, lead_id) is None:
            raise ApiError(404, "LEAD_NOT_FOUND", "The requested lead does not exist.")
        analysis = session.scalar(
            select(CompanyInsight)
            .where(CompanyInsight.lead_id == lead_id)
            .order_by(CompanyInsight.created_at.desc(), CompanyInsight.analysis_id.desc())
            .limit(1)
        )
        if analysis is None:
            raise ApiError(404, "ANALYSIS_NOT_FOUND", "No saved analysis exists for this lead.")
        score = session.scalar(
            select(LeadScore)
            .where(
                LeadScore.lead_id == lead_id,
                LeadScore.score == analysis.qualification_score,
                LeadScore.rationale == analysis.qualification_rationale,
            )
            .order_by(LeadScore.created_at.desc(), LeadScore.score_id.desc())
            .limit(1)
        )
        if score is None:
            raise ApiError(500, "ANALYSIS_INCONSISTENT", "Saved analysis is missing its qualification record.")
        return _analysis_output(analysis, score)

    @app.post(
        "/api/v1/leads/{lead_id}/conversation-summaries",
        response_model=ConversationSummaryOut,
        status_code=201,
    )
    def summarize_conversation(
        lead_id: int,
        payload: ConversationSummaryRequest,
        session: SessionDependency,
    ) -> ConversationSummaryOut:
        if session.get(Lead, lead_id) is None:
            raise ApiError(404, "LEAD_NOT_FOUND", "The requested lead does not exist.")
        try:
            content: ConversationContent = app.state.conversation_provider.summarize(
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

    @app.get(
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

    @app.get("/api/v1/crm/mappings")
    def get_crm_mappings() -> dict[str, dict[str, Any]]:
        mappings: dict[str, dict[str, Any]] = {}
        for provider_name, provider in app.state.crm_providers.items():
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

    @app.post(
        "/api/v1/leads/{lead_id}/crm-sync",
        response_model=CrmSyncOut,
    )
    def sync_lead_to_crm(
        lead_id: int,
        payload: CrmSyncRequest,
        session: SessionDependency,
    ) -> CrmSyncOut:
        lead = session.get(Lead, lead_id)
        if lead is None:
            raise ApiError(404, "LEAD_NOT_FOUND", "The requested lead does not exist.")
        provider: CrmSyncProvider | None = app.state.crm_providers.get(payload.provider)
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

    @app.get(
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

    @app.post(
        "/api/v1/leads/{lead_id}/scores",
        response_model=LeadScoreOut,
        status_code=201,
    )
    def create_lead_score(lead_id: int, session: SessionDependency) -> LeadScoreOut:
        lead = session.get(Lead, lead_id)
        if lead is None:
            raise ApiError(404, "LEAD_NOT_FOUND", "The requested lead does not exist.")
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        recent_activity_count = session.scalar(
            select(func.count())
            .select_from(Activity)
            .where(Activity.lead_id == lead_id, Activity.occurred_at >= cutoff)
        ) or 0
        conversation_count = session.scalar(
            select(func.count())
            .select_from(ConversationSummary)
            .where(ConversationSummary.lead_id == lead_id)
        ) or 0
        insight = session.scalar(
            select(CompanyInsight)
            .where(CompanyInsight.lead_id == lead_id)
            .order_by(CompanyInsight.created_at.desc(), CompanyInsight.analysis_id.desc())
            .limit(1)
        )
        score_value, rationale, factors, recommendation = score_sales_readiness(
            lead,
            insight,
            recent_activity_count=recent_activity_count,
            conversation_count=conversation_count,
        )
        score = LeadScore(
            lead_id=lead_id,
            score=score_value,
            rationale=rationale,
            factors=factors,
            recommendation=recommendation,
        )
        session.add(score)
        try:
            session.commit()
        except SQLAlchemyError as error:
            raise _database_failure(session, error) from error
        session.refresh(score)
        return _lead_score_output(score)

    @app.get(
        "/api/v1/leads/{lead_id}/scores/latest",
        response_model=LeadScoreOut,
    )
    def get_latest_lead_score(lead_id: int, session: SessionDependency) -> LeadScoreOut:
        if session.get(Lead, lead_id) is None:
            raise ApiError(404, "LEAD_NOT_FOUND", "The requested lead does not exist.")
        score = session.scalar(
            select(LeadScore)
            .where(
                LeadScore.lead_id == lead_id,
                LeadScore.recommendation.is_not(None),
            )
            .order_by(LeadScore.created_at.desc(), LeadScore.score_id.desc())
            .limit(1)
        )
        if score is None:
            raise ApiError(404, "SCORE_NOT_FOUND", "No Milestone 2 score exists for this lead.")
        return _lead_score_output(score)

    @app.post(
        "/api/v1/leads/{lead_id}/activities",
        response_model=ActivityOut,
        status_code=201,
    )
    def create_activity(
        lead_id: int, payload: ActivityCreate, session: SessionDependency
    ) -> ActivityOut:
        if session.get(Lead, lead_id) is None:
            raise ApiError(404, "LEAD_NOT_FOUND", "The requested lead does not exist.")
        activity = Activity(
            lead_id=lead_id,
            activity_type=payload.activity_type,
            details={"note": payload.details} if payload.details else {},
        )
        session.add(activity)
        try:
            session.commit()
        except SQLAlchemyError as error:
            raise _database_failure(session, error) from error
        session.refresh(activity)
        return ActivityOut.model_validate(activity)

    @app.get(
        "/api/v1/leads/{lead_id}/activities",
        response_model=list[ActivityOut],
    )
    def list_activities(lead_id: int, session: SessionDependency) -> list[ActivityOut]:
        if session.get(Lead, lead_id) is None:
            raise ApiError(404, "LEAD_NOT_FOUND", "The requested lead does not exist.")
        activities = session.scalars(
            select(Activity)
            .where(Activity.lead_id == lead_id)
            .order_by(Activity.occurred_at.desc(), Activity.activity_id.desc())
            .limit(100)
        ).all()
        return [ActivityOut.model_validate(activity) for activity in activities]

    @app.post(
        "/api/v1/leads/{lead_id}/outreach-drafts",
        response_model=OutreachDraftOut,
        status_code=201,
    )
    def generate_outreach_draft(
        lead_id: int,
        payload: OutreachGenerationRequest,
        session: SessionDependency,
    ) -> OutreachDraftOut:
        lead = session.get(Lead, lead_id)
        if lead is None:
            raise ApiError(404, "LEAD_NOT_FOUND", "The requested lead does not exist.")
        try:
            generated: OutreachContent = app.state.outreach_provider.generate(lead, payload)
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

    @app.get(
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

    @app.patch(
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

    return app


app = create_app()
