from __future__ import annotations

import json
import os
from typing import Protocol

from openai import OpenAI
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


class OpenAIAnalysisProvider:
    def __init__(self, api_key: str | None, model: str, timeout_seconds: float = 45) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(cls) -> OpenAIAnalysisProvider:
        return cls(
            api_key=os.getenv("OPENAI_API_KEY"),
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        )

    def analyze(self, lead: Lead, context: str | None) -> AnalysisContent:
        if not self.api_key:
            raise ProviderConfigurationError("OPENAI_API_KEY is not configured.")

        client = OpenAI(
            api_key=self.api_key,
            timeout=self.timeout_seconds,
            max_retries=1,
        )
        lead_context = {
            "company_name": lead.company_name,
            "industry": lead.industry,
            "contact_name": lead.contact_name,
            "lead_status": lead.lead_status,
            "user_supplied_context": context,
        }
        response = client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            max_completion_tokens=900,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Create cautious B2B company insights using only the supplied "
                        "lead fields and user notes. Do not invent or present external "
                        "company facts as verified. State uncertainty in the summary "
                        "when evidence is limited. Return JSON with exactly: summary "
                        "(string), potential_needs (array of strings), opportunities "
                        "(array of strings)."
                    ),
                },
                {"role": "user", "content": json.dumps(lead_context)},
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("The AI provider returned an empty analysis.")
        return AnalysisContent.model_validate_json(content)
