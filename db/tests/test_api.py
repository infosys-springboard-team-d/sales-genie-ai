from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.analysis import AnalysisContent, ProviderConfigurationError
from db.database import create_database_engine
from db.models import Base, CompanyInsight, ImportBatch, Lead, LeadScore
from main import create_app


class StubAnalysisProvider:
    def analyze(self, lead: Lead, context: str | None) -> AnalysisContent:
        return AnalysisContent(
            summary=f"{lead.company_name} is a synthetic test prospect.",
            potential_needs=["Improve reporting"],
            opportunities=["Review a reporting workflow"],
        )


class FailingAnalysisProvider:
    def analyze(self, lead: Lead, context: str | None) -> AnalysisContent:
        raise ProviderConfigurationError("Provider unavailable.")


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_database_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    app = create_app(engine=engine, analysis_provider=StubAnalysisProvider())
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


def create_lead(client: TestClient, **overrides: object) -> dict:
    lead_data = {
        "company_name": "Example Systems",
        "industry": "Software",
        "contact_name": "Jordan Lee",
        "email": "jordan@example.test",
        "phone": "+1-555-0100",
    }
    lead_data.update(overrides)
    response = client.post("/api/v1/leads", json=lead_data)
    assert response.status_code == 201
    return response.json()


def test_lead_create_search_retrieve_update_and_status(client: TestClient) -> None:
    lead = create_lead(client)

    search = client.get("/api/v1/leads", params={"q": "jordan@", "page": 1, "page_size": 10})
    assert search.status_code == 200
    assert search.json()["total"] == 1
    assert search.json()["items"][0]["lead_id"] == lead["lead_id"]

    retrieved = client.get(f"/api/v1/leads/{lead['lead_id']}")
    assert retrieved.status_code == 200
    assert retrieved.json()["company_name"] == "Example Systems"

    updated = client.patch(
        f"/api/v1/leads/{lead['lead_id']}",
        json={"industry": "Data Services"},
    )
    assert updated.status_code == 200
    assert updated.json()["industry"] == "Data Services"

    status = client.patch(
        f"/api/v1/leads/{lead['lead_id']}/status",
        json={"lead_status": "Qualified"},
    )
    assert status.status_code == 200
    assert status.json()["lead_status"] == "Qualified"


def test_duplicate_rules_and_explicit_unknown_lead_error(client: TestClient) -> None:
    lead = create_lead(client)
    duplicate_email = client.post(
        "/api/v1/leads",
        json={
            "company_name": "Different Company",
            "email": " JORDAN@example.test ",
        },
    )
    assert duplicate_email.status_code == 409
    assert duplicate_email.json()["error"]["code"] == "DUPLICATE_LEAD"

    no_email_match = client.post(
        "/api/v1/leads",
        json={
            "company_name": " example systems ",
            "contact_name": " jordan lee ",
        },
    )
    assert no_email_match.status_code == 409
    missing = client.get(f"/api/v1/leads/{lead['lead_id'] + 100}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "LEAD_NOT_FOUND"


def test_validation_error_uses_common_envelope(client: TestClient) -> None:
    response = client.post("/api/v1/leads", json={"company_name": " "})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"]


def test_csv_import_rolls_back_all_rows_when_any_row_is_invalid_or_duplicate(
    client: TestClient,
) -> None:
    create_lead(client)
    csv_content = (
        "company_name,industry,contact_name,email,phone,lead_status\n"
        "New Company,Technology,Sam Example,sam@example.test,,New\n"
        "Example Systems,Software,Jordan Lee,,,\n"
        ",Software,Missing Company,missing@example.test,,New\n"
        "Another Company,Software,Pat Example,jordan@example.test,,New\n"
    )
    response = client.post(
        "/api/v1/leads/import",
        files={"file": ("leads.csv", csv_content.encode(), "text/csv")},
    )
    assert response.status_code == 200
    result = response.json()
    assert (result["created"], result["duplicates"], result["rejected"]) == (0, 2, 1)
    assert result["committed"] is False
    assert result["duplicate_rows"] == [3, 5]
    assert result["rolled_back_rows"] == [2]
    assert any(issue["row"] == 4 for issue in result["row_errors"])
    assert (
        sum(result[key] for key in ("created", "duplicates", "rejected"))
        + len(result["rolled_back_rows"])
        == 4
    )

    with Session(client.app.state.engine) as session:
        batch = session.scalar(select(ImportBatch).order_by(ImportBatch.import_batch_id.desc()))
        assert batch is not None
        assert batch.status == "failed"
        assert (batch.created_count, batch.duplicate_count, batch.rejected_count) == (0, 2, 1)
        assert session.scalar(
            select(func.count()).select_from(Lead).where(Lead.company_name == "New Company")
        ) == 0


def test_csv_import_commits_complete_valid_file_and_detects_within_file_duplicates(
    client: TestClient,
) -> None:
    csv_content = (
        "company_name,industry,contact_name,email,phone,lead_status\n"
        "North Company,Technology,Jamie Lee,jamie@example.test,,New\n"
        "South Company,Technology,Taylor Smith,taylor@example.test,,New\n"
    )
    response = client.post(
        "/api/v1/leads/import",
        files={"file": ("clean.csv", csv_content.encode(), "text/csv")},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["committed"] is True
    assert result["created"] == 2
    assert result["duplicates"] == 0
    assert result["rejected"] == 0
    assert result["rolled_back_rows"] == []

    duplicate_csv = (
        "company_name,industry,contact_name,email,phone,lead_status\n"
        "Repeat Company,Technology,Alex Kim,alex@example.test,,New\n"
        " repeat company ,Technology, alex kim ,, ,New\n"
    )
    duplicate_response = client.post(
        "/api/v1/leads/import",
        files={"file": ("duplicates.csv", duplicate_csv.encode(), "text/csv")},
    )
    duplicate_result = duplicate_response.json()
    assert duplicate_result["committed"] is False
    assert duplicate_result["created"] == 0
    assert duplicate_result["duplicates"] == 1
    assert duplicate_result["rolled_back_rows"] == [2]
    with Session(client.app.state.engine) as session:
        assert session.scalar(
            select(func.count()).select_from(Lead).where(Lead.company_name == "Repeat Company")
        ) == 0


def test_analysis_is_saved_and_retrievable_for_same_lead(client: TestClient) -> None:
    lead = create_lead(client)
    response = client.post(
        f"/api/v1/leads/{lead['lead_id']}/analysis",
        json={"context": "Synthetic company research notes."},
    )
    assert response.status_code == 201
    analysis = response.json()
    assert analysis["lead_id"] == lead["lead_id"]
    assert analysis["qualification"]["score"] == 100
    assert analysis["qualification"]["factors"]["opportunities_identified"] == 20

    saved = client.get(f"/api/v1/leads/{lead['lead_id']}/analysis")
    assert saved.status_code == 200
    assert saved.json()["analysis_id"] == analysis["analysis_id"]

    with Session(client.app.state.engine) as session:
        assert session.scalar(select(func.count()).select_from(CompanyInsight)) == 1
        assert session.scalar(select(func.count()).select_from(LeadScore)) == 1


def test_analysis_provider_failure_never_returns_success_or_persists(
    client: TestClient,
) -> None:
    lead = create_lead(client)
    client.app.state.analysis_provider = FailingAnalysisProvider()
    response = client.post(f"/api/v1/leads/{lead['lead_id']}/analysis", json={})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AI_PROVIDER_NOT_CONFIGURED"
    saved = client.get(f"/api/v1/leads/{lead['lead_id']}/analysis")
    assert saved.status_code == 404


def test_no_analysis_and_invalid_status_are_explicit(client: TestClient) -> None:
    lead = create_lead(client)
    absent = client.get(f"/api/v1/leads/{lead['lead_id']}/analysis")
    assert absent.status_code == 404
    assert absent.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"

    invalid_status = client.patch(
        f"/api/v1/leads/{lead['lead_id']}/status",
        json={"lead_status": "Unknown"},
    )
    assert invalid_status.status_code == 400
    assert invalid_status.json()["error"]["code"] == "VALIDATION_ERROR"


def test_twenty_synthetic_leads_complete_supported_api_flow(client: TestClient) -> None:
    denominator = 20
    completed = 0
    for index in range(denominator):
        lead = create_lead(
            client,
            company_name=f"Synthetic Prospect {index}",
            contact_name=f"Contact {index}",
            email=f"contact{index}@example.test",
        )
        lead_id = lead["lead_id"]
        assert client.get(f"/api/v1/leads/{lead_id}").status_code == 200
        assert (
            client.patch(
                f"/api/v1/leads/{lead_id}",
                json={"industry": "Synthetic Services"},
            ).status_code
            == 200
        )
        assert (
            client.patch(
                f"/api/v1/leads/{lead_id}/status",
                json={"lead_status": "Contacted"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/v1/leads/{lead_id}/analysis",
                json={"context": "Synthetic acceptance-test context."},
            ).status_code
            == 201
        )
        assert client.get(f"/api/v1/leads/{lead_id}/analysis").status_code == 200
        completed += 1
    assert completed / denominator >= 0.95
