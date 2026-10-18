from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.analysis import AnalysisContent
from db.database import create_database_engine
from db.models import CompanyInsight, ImportBatch, Lead, LeadScore
from main import create_app


class PostgresTestAnalysisProvider:
    def analyze(self, lead: Lead, context: str | None) -> AnalysisContent:
        return AnalysisContent(
            summary=f"Synthetic PostgreSQL analysis for {lead.company_name}.",
            potential_needs=["Improve reporting"],
            opportunities=["Review reporting workflows"],
        )


@pytest.fixture
def postgres_client() -> Iterator[tuple[TestClient, str, str, str]]:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url or not database_url.startswith("postgresql"):
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration coverage.")
    engine = create_database_engine(database_url)
    token = uuid4().hex
    lead_company = f"Postgres API Lead {token}"
    csv_company = f"Postgres CSV Lead {token}"
    rejected_filename = f"postgres-rejected-{token}.csv"
    client = TestClient(
        create_app(
            engine=engine,
            analysis_provider=PostgresTestAnalysisProvider(),
        )
    )
    try:
        yield client, token, lead_company, csv_company
    finally:
        with Session(engine) as session, session.begin():
            lead_ids = select(Lead.lead_id).where(
                Lead.company_name.in_([lead_company, csv_company])
            )
            session.execute(
                delete(CompanyInsight).where(CompanyInsight.lead_id.in_(lead_ids))
            )
            session.execute(delete(LeadScore).where(LeadScore.lead_id.in_(lead_ids)))
            session.execute(delete(Lead).where(Lead.lead_id.in_(lead_ids)))
            session.execute(
                delete(ImportBatch).where(ImportBatch.filename == rejected_filename)
            )
        engine.dispose()


def test_postgresql_milestone_flow_and_atomic_csv(
    postgres_client: tuple[TestClient, str, str, str],
) -> None:
    client, token, lead_company, csv_company = postgres_client
    create_response = client.post(
        "/api/v1/leads",
        json={
            "company_name": lead_company,
            "industry": "Synthetic QA",
            "contact_name": "Database Tester",
            "email": f"{token}@example.test",
        },
    )
    assert create_response.status_code == 201
    lead_id = create_response.json()["lead_id"]
    assert client.get(f"/api/v1/leads/{lead_id}").status_code == 200
    assert client.patch(
        f"/api/v1/leads/{lead_id}/status",
        json={"lead_status": "Qualified"},
    ).status_code == 200

    analysis_response = client.post(
        f"/api/v1/leads/{lead_id}/analysis",
        json={"context": "PostgreSQL integration-test context."},
    )
    assert analysis_response.status_code == 201
    assert client.get(f"/api/v1/leads/{lead_id}/analysis").json()["lead_id"] == lead_id

    csv_data = (
        "company_name,industry,contact_name,email,phone,lead_status\n"
        f"{csv_company},Software,Unique Contact,{token}-csv@example.test,,New\n"
        f"Another Company,Software,Duplicate Contact,{token}@example.test,,New\n"
    )
    import_response = client.post(
        "/api/v1/leads/import",
        files={
            "file": (
                f"postgres-rejected-{token}.csv",
                csv_data.encode(),
                "text/csv",
            )
        },
    )
    assert import_response.status_code == 200
    result = import_response.json()
    assert result["committed"] is False
    assert result["created"] == 0
    assert result["duplicates"] == 1
    assert result["rolled_back_rows"] == [2]

    with Session(client.app.state.engine) as session:
        assert session.scalar(
            select(Lead.lead_id).where(Lead.company_name == csv_company)
        ) is None
