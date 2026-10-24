from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import requests

from api.analysis import AnalysisProviderError, OllamaAnalysisProvider
from db.models import Lead


def test_ollama_provider_parses_analysis_response() -> None:
    response = Mock()
    response.json.return_value = {
        "message": {
            "content": (
                '{"summary":"A software company.",'
                '"potential_needs":["Reporting"],'
                '"opportunities":["Review analytics"]}'
            )
        }
    }
    lead = Lead(
        company_name="Example Systems",
        industry="Software",
        contact_name="Alex Example",
        lead_status="New",
    )
    provider = OllamaAnalysisProvider("http://localhost:11434/", "llama3.2:latest")

    with patch("api.analysis.requests.post", return_value=response) as post:
        result = provider.analyze(lead, "Synthetic test context")

    assert result.summary == "A software company."
    assert result.potential_needs == ["Reporting"]
    assert result.opportunities == ["Review analytics"]
    args, kwargs = post.call_args
    assert args[0] == "http://localhost:11434/api/chat"
    assert kwargs["json"]["model"] == "llama3.2:latest"
    assert kwargs["json"]["stream"] is False
    assert kwargs["json"]["messages"][1]["content"].find("Synthetic test context") >= 0


def test_ollama_provider_reports_unavailable_service() -> None:
    provider = OllamaAnalysisProvider("http://localhost:11434", "llama3.2:latest")
    lead = Lead(company_name="Example Systems", lead_status="New")

    with (
        patch(
            "api.analysis.requests.post",
            side_effect=requests.ConnectionError("connection refused"),
        ),
        pytest.raises(AnalysisProviderError, match="Start Ollama"),
    ):
        provider.analyze(lead, None)


def test_ollama_provider_rejects_invalid_analysis_json() -> None:
    response = Mock()
    response.json.return_value = {"message": {"content": '{"summary": 5}'}}
    provider = OllamaAnalysisProvider("http://localhost:11434", "llama3.2:latest")
    lead = Lead(company_name="Example Systems", lead_status="New")

    with (
        patch("api.analysis.requests.post", return_value=response),
        pytest.raises(AnalysisProviderError, match="unexpected format"),
    ):
        provider.analyze(lead, None)
