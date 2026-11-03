from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import requests

from api.outreach import (
    OllamaOutreachProvider,
    OutreachContent,
    OutreachProviderError,
)
from api.schemas import OutreachGenerationRequest
from db.models import Lead


def test_ollama_outreach_provider_parses_a_personalized_email() -> None:
    response = Mock()
    response.json.return_value = {
        "message": {
            "content": (
                '{"subject":"A reporting idea","body":"Hello Alex, '
                'would a short discussion about reporting be useful?"}'
            )
        }
    }
    provider = OllamaOutreachProvider("http://localhost:11434/", "llama3.2:latest")
    lead = Lead(
        company_name="Example Systems",
        industry="Software",
        contact_name="Alex Example",
        lead_status="New",
    )
    request = OutreachGenerationRequest(
        draft_type="email",
        goal="Start a conversation",
        pain_points=["Manual reporting"],
    )

    with patch("api.outreach.requests.post", return_value=response) as post:
        result = provider.generate(lead, request)

    assert result.subject == "A reporting idea"
    assert "Hello Alex" in result.body
    args, kwargs = post.call_args
    assert args[0] == "http://localhost:11434/api/chat"
    assert kwargs["json"]["model"] == "llama3.2:latest"
    assert kwargs["json"]["stream"] is False
    schema = kwargs["json"]["format"]
    assert schema["properties"]["subject"] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 300,
        "description": "A concise subject that names the supplied pain point or goal.",
    }
    assert schema["required"] == ["subject", "body"]
    assert kwargs["json"]["options"]["temperature"] == 0.25
    assert kwargs["json"]["options"]["top_p"] == 0.9
    assert "Manual reporting" in kwargs["json"]["messages"][1]["content"]
    prompt = kwargs["json"]["messages"][0]["content"]
    assert "Your notes mention" in prompt
    assert "do not claim 'we can help'" in prompt
    assert "A question about inventory reconciliation" in prompt
    assert "low-pressure CTA aligned with the goal" in prompt


def test_ollama_outreach_provider_surfaces_unavailable_service() -> None:
    provider = OllamaOutreachProvider("http://localhost:11434", "llama3.2:latest")
    lead = Lead(company_name="Example Systems", lead_status="New")
    request = OutreachGenerationRequest(goal="Ask for a meeting")

    with (
        patch(
            "api.outreach.requests.post",
            side_effect=requests.ConnectionError("connection refused"),
        ),
        pytest.raises(OutreachProviderError, match="Start Ollama"),
    ):
        provider.generate(lead, request)


def test_ollama_outreach_provider_rejects_missing_email_subject() -> None:
    response = Mock()
    response.json.return_value = {
        "message": {"content": '{"subject":null,"body":"Hello there."}'}
    }
    provider = OllamaOutreachProvider("http://localhost:11434", "llama3.2:latest")
    lead = Lead(company_name="Example Systems", lead_status="New")
    request = OutreachGenerationRequest(goal="Ask for a meeting")

    with (
        patch("api.outreach.requests.post", return_value=response),
        pytest.raises(OutreachProviderError, match="email subject"),
    ):
        provider.generate(lead, request)
