from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
import json
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.conversations import ConversationContent, ConversationProviderError
from api.crm import HubSpotCrmProvider, SalesforceCrmProvider
from api.schemas import ConversationSummaryRequest
from db.database import create_database_engine
from db.models import Activity, Base, ConversationSummary, CrmSyncLog, Lead
from main import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class StubConversationProvider:
    def summarize(self, interaction_type: str, transcript: str) -> ConversationContent:
        return ConversationContent(
            summary=f"Synthetic {interaction_type} summary.",
            key_points=["The prospect asked about reporting."],
            action_items=["Sales owner to send the requested overview."],
        )


class FailingConversationProvider:
    def summarize(self, interaction_type: str, transcript: str) -> ConversationContent:
        raise ConversationProviderError("Ollama is unavailable.")


class StubCrmProvider:
    def __init__(
        self,
        *,
        configured: bool = True,
        deal_stage_mapping: dict[str, str] | None = None,
        fail_activities: bool = False,
    ) -> None:
        self.configured = configured
        self.status_mapping = {"New": "lead"}
        self.deal_stage_mapping = deal_stage_mapping or {}
        self.fail_activities = fail_activities
        self.contact_calls: list[tuple[int, str | None]] = []
        self.activity_calls: list[tuple[str, str]] = []
        self.deal_calls: list[tuple[str, str]] = []

    def is_configured(self) -> bool:
        return self.configured

    def sync_contact(self, lead: Lead, external_id: str | None) -> str:
        self.contact_calls.append((lead.lead_id, external_id))
        return external_id or f"remote-contact-{lead.lead_id}"

    def sync_activity(
        self, contact_id: str, activity: Activity, external_id: str | None = None
    ) -> str:
        if self.fail_activities:
            from api.crm import CrmProviderError

            raise CrmProviderError(
                "CRM_PROVIDER_ERROR",
                "Activity sync failed.",
                external_id=external_id,
            )
        note = activity.details.get("note", "")
        self.activity_calls.append((contact_id, note))
        return f"remote-activity-{len(self.activity_calls)}"

    def stage_for_status(self, lead_status: str) -> str | None:
        return self.deal_stage_mapping.get(lead_status)

    def sync_deal_stage(self, deal_id: str, stage: str) -> str:
        self.deal_calls.append((deal_id, stage))
        return deal_id


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_database_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    crm_provider = StubCrmProvider(deal_stage_mapping={"New": "qualified"})
    app = create_app(
        engine=engine,
        conversation_provider=StubConversationProvider(),
        crm_providers={"salesforce": crm_provider, "hubspot": crm_provider},
    )
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


def create_lead(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/leads",
        json={
            "company_name": "Example Systems",
            "contact_name": "Jordan Lee",
            "email": "jordan@example.test",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_conversation_summary_is_saved_and_retrievable_without_transcript(
    client: TestClient,
) -> None:
    lead = create_lead(client)
    response = client.post(
        f"/api/v1/leads/{lead['lead_id']}/conversation-summaries",
        json={
            "interaction_type": "meeting",
            "transcript": "A synthetic call transcript with a clear next step.",
        },
    )

    assert response.status_code == 201
    summary = response.json()
    assert summary["lead_id"] == lead["lead_id"]
    assert summary["interaction_type"] == "meeting"
    assert summary["action_items"] == [
        "Sales owner to send the requested overview."
    ]
    assert "transcript" not in summary
    assert client.get(
        f"/api/v1/leads/{lead['lead_id']}/conversation-summaries"
    ).json()[0]["summary_id"] == summary["summary_id"]

    with Session(client.app.state.engine) as session:
        assert session.scalar(
            select(func.count()).select_from(ConversationSummary)
        ) == 1
        columns = {column["name"] for column in inspect(session.bind).get_columns(
            "conversation_summaries"
        )}
        assert "transcript" not in columns


def test_conversation_provider_failure_does_not_save_a_summary(
    client: TestClient,
) -> None:
    lead = create_lead(client)
    client.app.state.conversation_provider = FailingConversationProvider()

    response = client.post(
        f"/api/v1/leads/{lead['lead_id']}/conversation-summaries",
        json={"transcript": "Synthetic transcript."},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "AI_PROVIDER_ERROR"
    assert client.get(
        f"/api/v1/leads/{lead['lead_id']}/conversation-summaries"
    ).json() == []


def test_conversation_request_rejects_blank_and_oversized_transcripts(
    client: TestClient,
) -> None:
    lead = create_lead(client)
    blank = client.post(
        f"/api/v1/leads/{lead['lead_id']}/conversation-summaries",
        json={"transcript": "  "},
    )
    oversized = client.post(
        f"/api/v1/leads/{lead['lead_id']}/conversation-summaries",
        json={"transcript": "x" * 40001},
    )

    assert blank.status_code == 422
    assert oversized.status_code == 422


def test_synthetic_sample_transcripts_match_summary_request_contract() -> None:
    dataset = json.loads(
        (PROJECT_ROOT / "resource" / "milestone_3_sample_transcripts.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(dataset["cases"]) == 2
    for case in dataset["cases"]:
        request = ConversationSummaryRequest.model_validate(
            {
                "interaction_type": case["interaction_type"],
                "transcript": case["transcript"],
            }
        )
        assert request.transcript
        assert case["expected_facts"]
        assert case["expected_action_items"]


def test_crm_sync_sends_contacts_activities_and_existing_deal_stage_once(
    client: TestClient,
) -> None:
    lead = create_lead(client)
    client.post(
        f"/api/v1/leads/{lead['lead_id']}/activities",
        json={"activity_type": "call", "details": "Discussed a synthetic use case."},
    )
    client.post(
        f"/api/v1/leads/{lead['lead_id']}/conversation-summaries",
        json={"interaction_type": "meeting", "transcript": "Synthetic transcript."},
    )
    provider = client.app.state.crm_providers["hubspot"]

    payload = {
        "provider": "hubspot",
        "include_activities": True,
        "deal_id": "existing-deal-42",
    }
    first = client.post(f"/api/v1/leads/{lead['lead_id']}/crm-sync", json=payload)

    assert first.status_code == 200
    result = first.json()
    assert result["status"] == "succeeded"
    assert result["activities_synced"] == 2
    assert result["deal_stage_status"] == "succeeded"
    assert len(provider.activity_calls) == 2
    assert any("Action items:" in note for _, note in provider.activity_calls)
    assert provider.deal_calls == [("existing-deal-42", "qualified")]

    second = client.post(f"/api/v1/leads/{lead['lead_id']}/crm-sync", json=payload)
    assert second.status_code == 200
    assert second.json()["activities_synced"] == 0
    assert len(provider.activity_calls) == 2
    assert len(provider.deal_calls) == 1
    with Session(client.app.state.engine) as session:
        assert session.scalar(select(func.count()).select_from(CrmSyncLog)) == 5


def test_crm_sync_reports_partial_activity_failures(client: TestClient) -> None:
    lead = create_lead(client)
    client.post(
        f"/api/v1/leads/{lead['lead_id']}/activities",
        json={"activity_type": "email", "details": "Synthetic email activity."},
    )
    client.app.state.crm_providers["hubspot"].fail_activities = True

    response = client.post(
        f"/api/v1/leads/{lead['lead_id']}/crm-sync",
        json={"provider": "hubspot"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "partial"
    assert response.json()["activities_failed"] == 1
    assert response.json()["operations"][-1]["error_code"] == "CRM_PROVIDER_ERROR"
    logs = client.get(f"/api/v1/leads/{lead['lead_id']}/crm-sync-logs").json()
    assert any(log["status"] == "failed" and log["entity_type"] == "activity" for log in logs)


def test_crm_sync_requires_configured_credentials_and_records_failure(
    client: TestClient,
) -> None:
    lead = create_lead(client)
    client.app.state.crm_providers["hubspot"].configured = False

    response = client.post(
        f"/api/v1/leads/{lead['lead_id']}/crm-sync",
        json={"provider": "hubspot"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CRM_PROVIDER_NOT_CONFIGURED"
    log = client.get(f"/api/v1/leads/{lead['lead_id']}/crm-sync-logs").json()[0]
    assert log["status"] == "failed"
    assert log["error_code"] == "CRM_NOT_CONFIGURED"


def test_deal_stage_is_not_updated_without_an_explicit_mapping(
    client: TestClient,
) -> None:
    lead = create_lead(client)
    provider = client.app.state.crm_providers["hubspot"]
    provider.deal_stage_mapping = {}

    response = client.post(
        f"/api/v1/leads/{lead['lead_id']}/crm-sync",
        json={"provider": "hubspot", "deal_id": "existing-deal-42"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CRM_STAGE_MAPPING_NOT_CONFIGURED"
    assert provider.contact_calls == []
    assert provider.deal_calls == []


def test_crm_mapping_status_excludes_credentials(client: TestClient) -> None:
    provider = client.app.state.crm_providers["hubspot"]
    provider.token = "must-not-be-returned"
    response = client.get("/api/v1/crm/mappings")

    assert response.status_code == 200
    assert response.json()["hubspot"]["configured"] is True
    assert "must-not-be-returned" not in response.text


class FakeCrmResponse:
    def __init__(self, payload: dict | None = None, status_code: int = 200) -> None:
        self.payload = payload or {}
        self.status_code = status_code
        self.content = b"" if status_code == 204 else b"{}"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(response=response)

    def json(self) -> dict:
        return self.payload


def test_salesforce_adapter_maps_contacts_activities_and_existing_deal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []
    responses = iter(
        [
            FakeCrmResponse({"records": []}),
            FakeCrmResponse({"id": "00Q000000000001"}),
            FakeCrmResponse({"id": "00T000000000001"}),
            FakeCrmResponse(status_code=204),
        ]
    )

    def fake_request(method: str, url: str, **kwargs: dict) -> FakeCrmResponse:
        calls.append({"method": method, "url": url, **kwargs})
        return next(responses)

    monkeypatch.setattr("api.crm.requests.request", fake_request)
    provider = SalesforceCrmProvider(
        instance_url="https://example.salesforce.com",
        token="salesforce-test-token",
        deal_stage_mapping={"New": "Qualification"},
    )
    lead = Lead(
        lead_id=1,
        company_name="Example Systems",
        contact_name="Jordan Lee",
        email="jordan@example.test",
        lead_status="New",
    )
    contact_id = provider.sync_contact(lead, None)
    activity_id = provider.sync_activity(
        contact_id,
        Activity(
            activity_type="call",
            details={"note": "Synthetic call note."},
            occurred_at=datetime(2026, 11, 7),
        ),
    )
    provider.sync_deal_stage("006000000000001", "Qualification")

    assert contact_id == "00Q000000000001"
    assert activity_id == "00T000000000001"
    assert calls[0]["method"] == "GET"
    assert calls[1]["method"] == "POST"
    assert calls[1]["json"]["Company"] == "Example Systems"
    assert calls[1]["json"]["FirstName"] == "Jordan"
    assert calls[1]["json"]["LastName"] == "Lee"
    assert calls[1]["json"]["Status"] == "Open - Not Contacted"
    assert calls[2]["json"]["WhoId"] == contact_id
    assert calls[3]["url"].endswith("/sobjects/Opportunity/006000000000001")
    assert calls[3]["json"] == {"StageName": "Qualification"}
    assert calls[0]["headers"]["Authorization"] == "Bearer salesforce-test-token"


def test_hubspot_adapter_maps_contact_task_and_existing_deal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []
    responses = iter(
        [
            FakeCrmResponse({"results": []}),
            FakeCrmResponse({"id": "12345"}),
            FakeCrmResponse({"id": "67890"}),
            FakeCrmResponse(status_code=204),
            FakeCrmResponse(status_code=204),
        ]
    )

    def fake_request(method: str, url: str, **kwargs: dict) -> FakeCrmResponse:
        calls.append({"method": method, "url": url, **kwargs})
        return next(responses)

    monkeypatch.setattr("api.crm.requests.request", fake_request)
    provider = HubSpotCrmProvider(
        token="hubspot-test-token",
        deal_stage_mapping={"New": "appointmentscheduled"},
    )
    lead = Lead(
        lead_id=1,
        company_name="Example Systems",
        contact_name="Jordan Lee",
        email="jordan@example.test",
        lead_status="New",
    )
    contact_id = provider.sync_contact(lead, None)
    task_id = provider.sync_activity(
        contact_id,
        Activity(
            activity_type="meeting",
            details={"note": "Synthetic meeting note."},
            occurred_at=datetime(2026, 11, 7),
        ),
    )
    provider.sync_deal_stage("98765", "appointmentscheduled")

    assert contact_id == "12345"
    assert task_id == "67890"
    assert calls[1]["json"]["properties"]["company"] == "Example Systems"
    assert calls[1]["json"]["properties"]["lifecyclestage"] == "lead"
    assert calls[2]["json"]["properties"]["hs_task_body"] == "Synthetic meeting note."
    assert "/associations/default/contacts/12345" in calls[3]["url"]
    assert calls[4]["json"]["properties"] == {
        "dealstage": "appointmentscheduled"
    }
    assert calls[0]["headers"]["Authorization"] == "Bearer hubspot-test-token"
