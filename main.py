from __future__ import annotations

import csv
import io
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from openai import OpenAIError
from sqlalchemy import func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from pydantic import ValidationError

from api.analysis import (
    AnalysisContent,
    AnalysisProvider,
    OpenAIAnalysisProvider,
    ProviderConfigurationError,
)
from api.schemas import (
    AnalysisOut,
    AnalysisRequest,
    CsvLeadInput,
    ImportResult,
    LeadCreate,
    LeadOut,
    LeadPage,
    LeadPatch,
    LeadStatus,
    LeadStatusUpdate,
)
from api.scoring import score_lead
from db.database import create_database_engine
from db.models import CompanyInsight, ImportBatch, Lead, LeadScore


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


def _database_failure(session: Session, error: SQLAlchemyError) -> ApiError:
    session.rollback()
    logger.error("Database operation failed (%s)", type(error).__name__)
    return ApiError(503, "DATABASE_UNAVAILABLE", "The database operation could not be completed.")


def create_app(
    database_url: str | None = None,
    analysis_provider: AnalysisProvider | None = None,
    engine: Engine | None = None,
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
        description="Milestone 1 lead management and saved company intelligence.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.session_factory = session_factory
    app.state.engine = database_engine
    app.state.analysis_provider = analysis_provider or OpenAIAnalysisProvider.from_environment()

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
            if request.method == "POST" and request.url.path.endswith("/analysis")
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
        except OpenAIError as error:
            logger.warning("AI provider request failed (%s)", type(error).__name__)
            raise ApiError(502, "AI_PROVIDER_ERROR", "Company analysis could not be generated.") from error
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
            .where(LeadScore.lead_id == lead_id)
            .order_by(LeadScore.created_at.desc(), LeadScore.score_id.desc())
            .limit(1)
        )
        if score is None:
            raise ApiError(500, "ANALYSIS_INCONSISTENT", "Saved analysis is missing its qualification record.")
        return _analysis_output(analysis, score)

    return app


app = create_app()
