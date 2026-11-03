from __future__ import annotations

import json
import os
from typing import Protocol

import requests
from pydantic import BaseModel, ConfigDict, Field

from api.schemas import OutreachGenerationRequest
from db.models import Lead


class OutreachContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str | None = Field(
        default=None,
        max_length=300,
        description="A concise email subject, or null for a message draft.",
    )
    body: str = Field(
        min_length=1,
        max_length=5000,
        description=(
            "A human-review-ready sales draft that follows the requested tone, "
            "length, goal, and draft type."
        ),
    )


class OutreachProvider(Protocol):
    def generate(
        self, lead: Lead, request: OutreachGenerationRequest
    ) -> OutreachContent: ...


class OutreachProviderConfigurationError(Exception):
    pass


class OutreachProviderError(Exception):
    pass


class OllamaOutreachProvider:
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
    def from_environment(cls) -> OllamaOutreachProvider:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip()
        model = os.getenv("OLLAMA_MODEL", "llama3.2:latest").strip()
        if not base_url or not model:
            raise OutreachProviderConfigurationError(
                "OLLAMA_BASE_URL and OLLAMA_MODEL must be configured."
            )
        return cls(base_url, model)

    def generate(
        self, lead: Lead, request: OutreachGenerationRequest
    ) -> OutreachContent:
        supplied_context = {
            "company_name": lead.company_name,
            "industry": lead.industry,
            "contact_name": lead.contact_name,
            "lead_status": lead.lead_status,
            "draft_type": request.draft_type,
            "tone": request.tone,
            "length": request.length,
            "goal": request.goal,
            "pain_points": request.pain_points,
        }
        response_schema = OutreachContent.model_json_schema()
        if request.draft_type == "email":
            response_schema["properties"]["subject"] = {
                "type": "string",
                "minLength": 1,
                "maxLength": 300,
                "description": "A concise subject that names the supplied pain point or goal.",
            }
            response_schema["required"] = ["subject", "body"]

        if request.draft_type == "email":
            system_prompt = (
                "Write a polished, useful B2B sales email. Ground every specific "
                "statement in the supplied fields; do not make up praise, research, "
                "products, tools, results, metrics, current processes, or sender "
                "capabilities. A pain point is a user-provided note, so describe it "
                "as a note and say 'if it is still a priority'; never say you noticed "
                "it or that it is definitely happening. No sender company or offering "
                "is supplied, so do not claim 'we can help'. Avoid generic openings. "
                "Copy the style and evidence discipline of this example, not its facts: "
                'Input: company Cedar Works; contact Maya; pain point inventory '
                'reconciliation; goal start a conversation; medium email. '
                'Output: {"subject":"A question about inventory reconciliation",'
                '"body":"Hi Maya,\\n\\nYour notes mention inventory reconciliation '
                'at Cedar Works. If that is still a priority, which step takes the '
                'most effort today? A useful first conversation could focus on '
                'whether a simpler process is worth exploring. Would you be open '
                'to a short call to compare notes?\\n\\nBest, [Your name]"} '
                "For this email, use a short subject that gives a reason to open "
                "and directly names the supplied pain point or goal (not only a "
                "topic label). Greet the supplied contact, mention only the exact "
                "company and pain point as 'your notes mention...', phrase relevance "
                "conditionally, add one concrete discovery question and one "
                "low-pressure CTA aligned with the goal. Medium body should have "
                "3-5 purposeful sentences excluding greeting and sign-off; scale "
                "short and long accordingly. Keep the requested tone, avoid filler, "
                "and end with 'Best, [Your name]'. The subject is required and must "
                "not be empty. The draft is for human review and must not imply it "
                "has been sent. Return only JSON matching the supplied schema."
            )
        else:
            system_prompt = (
                "Write one natural, respectful B2B message using only the supplied "
                "lead details and user-provided pain points. Treat pain points as "
                "unverified notes, do not invent company details, products, results, "
                "prior contact, referrals, urgency, or promises, and do not claim "
                "sender capabilities that were not supplied. Refer to a pain point "
                "conditionally if appropriate, tie the message to a specific supplied "
                "detail, make one clear low-pressure call to action, and avoid generic "
                "claims or filler. Follow the requested tone, goal, and length. Do "
                "not include a subject or email sign-off. The draft is for human "
                "review and must not imply it has been sent. Return only JSON "
                "matching the supplied schema."
            )
        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "format": response_schema,
                    "options": {
                        "temperature": 0.25,
                        "top_p": 0.9,
                        "repeat_penalty": 1.05,
                        "num_predict": 900,
                    },
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(supplied_context)},
                    ],
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as error:
            raise OutreachProviderError(
                "Could not reach Ollama. Start Ollama and confirm the configured "
                "model is installed."
            ) from error
        except ValueError as error:
            raise OutreachProviderError(
                "Ollama returned an invalid outreach response."
            ) from error

        message = payload.get("message") if isinstance(payload, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise OutreachProviderError(
                "Ollama returned an empty outreach draft. Check that the model is available."
            )
        try:
            result = OutreachContent.model_validate_json(content)
        except ValueError as error:
            raise OutreachProviderError(
                "Ollama returned outreach content in an unexpected format."
            ) from error
        if request.draft_type == "email" and not result.subject:
            raise OutreachProviderError(
                "Ollama did not provide an email subject. Please regenerate the draft."
            )
        if request.draft_type == "message" and result.subject:
            return result.model_copy(update={"subject": None})
        return result
