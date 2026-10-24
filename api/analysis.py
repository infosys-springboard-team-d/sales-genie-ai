from __future__ import annotations

import json
import os
from typing import Protocol

import requests
from pydantic import BaseModel, ConfigDict, Field

from db.models import Lead


class AnalysisContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=4000)
    potential_needs: list[str] = Field(max_length=20)
    opportunities: list[str] = Field(max_length=20)


class AnalysisProvider(Protocol):
    def analyze(self, lead: Lead, context: str | None) -> AnalysisContent: ...


class ProviderConfigurationError(Exception):
    pass


class AnalysisProviderError(Exception):
    pass


class OllamaAnalysisProvider:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float = 180,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(cls) -> OllamaAnalysisProvider:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip()
        model = os.getenv("OLLAMA_MODEL", "llama3.2:latest").strip()
        if not base_url or not model:
            raise ProviderConfigurationError(
                "OLLAMA_BASE_URL and OLLAMA_MODEL must be configured."
            )
        return cls(
            base_url=base_url,
            model=model,
        )

    def analyze(self, lead: Lead, context: str | None) -> AnalysisContent:
        lead_context = {
            "company_name": lead.company_name,
            "industry": lead.industry,
            "contact_name": lead.contact_name,
            "lead_status": lead.lead_status,
            "user_supplied_context": context,
        }
        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "format": "json",
                    "options": {"num_predict": 900},
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Create cautious B2B company insights using only the "
                                "supplied lead fields and user notes. Do not invent or "
                                "present external company facts as verified. State "
                                "uncertainty in the summary when evidence is limited. "
                                "Return JSON with exactly: summary (string), "
                                "potential_needs (array of strings), opportunities "
                                "(array of strings)."
                            ),
                        },
                        {"role": "user", "content": json.dumps(lead_context)},
                    ],
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as error:
            raise AnalysisProviderError(
                "Could not reach Ollama. Start Ollama and confirm the configured "
                "model is installed."
            ) from error
        except ValueError as error:
            raise AnalysisProviderError(
                "Ollama returned an invalid response."
            ) from error

        message = body.get("message") if isinstance(body, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise AnalysisProviderError(
                "Ollama returned an empty analysis. Check that the model is available."
            )
        try:
            return AnalysisContent.model_validate_json(content)
        except ValueError as error:
            raise AnalysisProviderError(
                "Ollama returned analysis in an unexpected format."
            ) from error
