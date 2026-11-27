from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from api.analysis import AnalysisProvider, OllamaAnalysisProvider
from api.conversations import ConversationProvider, OllamaConversationProvider
from api.crm import CrmSyncProvider, HubSpotCrmProvider, SalesforceCrmProvider
from api.deps import ApiError
from api.outreach import OllamaOutreachProvider, OutreachProvider
from api.routes.analytics import router as analytics_router
from api.routes.conversations import router as conversations_router
from api.routes.crm import router as crm_router
from api.routes.leads import router as leads_router
from api.routes.outreach import router as outreach_router
from db.database import create_database_engine

load_dotenv()
logger = logging.getLogger(__name__)


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

    for router in (
        leads_router,
        conversations_router,
        crm_router,
        outreach_router,
        analytics_router,
    ):
        app.router.routes.extend(router.routes)

    return app


app = create_app()
