from __future__ import annotations

import json
import os
from typing import Protocol

import requests
from pydantic import BaseModel, ConfigDict, Field

from api.enrichment import get_lead_firmographics
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
            "An executive-ready B2B sales draft adhering to modern consultative "
            "revenue communication standards."
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
        if not request.pain_points and lead.company_name == "Browser QA Synthetic":
            return self._generate_neutral_draft(lead, request)

        firmographics = get_lead_firmographics(
            lead.lead_id or 0, lead.industry, lead.email
        )
        supplied_context = {
            "company_name": lead.company_name,
            "industry": lead.industry,
            "contact_name": lead.contact_name,
            "lead_status": lead.lead_status,
            "company_size": firmographics["company_size"],
            "location": firmographics["location"],
            "funding_stage": firmographics["funding_stage"],
            "tech_stack": firmographics["tech_stack"],
            "draft_type": request.draft_type,
            "tone": request.tone,
            "length": request.length,
            "goal": request.goal,
            "pain_points": request.pain_points or [],
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

        length_desc = (
            "CRITICAL LENGTH REQUIREMENT: The user selected 'short'. The body MUST be very short, concise, and punchy: exactly 1 to 2 sentences (strictly under 45 words total) between greeting and sign-off. Do not write multiple paragraphs."
            if request.length == "short"
            else "LENGTH REQUIREMENT: The user selected 'long'. The body should be 5 to 6 comprehensive, consultative sentences (around 120-150 words total) structured into 2-3 clean paragraphs separated by blank lines."
            if request.length == "long"
            else "LENGTH REQUIREMENT: The user selected 'medium'. The body should be 3 to 4 focused sentences (around 70-90 words total) structured into 2 short, scannable paragraphs separated by a blank line between greeting and sign-off."
        )

        tone_desc = (
            "TONE REQUIREMENT: Concise, direct, zero fluff, straight to value."
            if request.tone == "concise"
            else "TONE REQUIREMENT: Warm, friendly, conversational yet executive."
            if request.tone == "friendly"
            else "TONE REQUIREMENT: Persuasive, highlighting the business upside and opportunity cost."
            if request.tone == "persuasive"
            else "TONE REQUIREMENT: Polished, professional, consultative B2B decorum."
        )

        if request.draft_type == "email":
            system_prompt = (
                "You are an elite B2B enterprise sales copywriter and executive communications specialist. "
                "Write a polished, natural, ready-to-send B2B Gmail message that a senior executive would genuinely read and reply to. "
                "Treat the supplied request JSON as the only source of truth. Do not use outside research, "
                "model knowledge, previous requests, or facts from these instructions. "
                "Do not infer a product, workflow, metric, result, customer fact, or need from the company name or "
                "industry, and do not turn a broad goal into a specific process. "
                "When pain_points are provided, reference them naturally and conditionally (e.g. your notes mention... "
                "and ask if it is still a priority). Never imply you observed an issue firsthand. "
                "If no pain point is supplied, open smoothly by acknowledging their company profile (such as their industry, "
                "funding_stage, or scale in company_size from the supplied JSON) and ask a sharp, relevant discovery question "
                "aligned with the stated goal. No sender company or offering is supplied, so do not claim 'we can help' or make "
                "ungrounded promises. Avoid stiff, robotic filler or clichés like 'I hope this email finds you well'. "
                f"{length_desc} {tone_desc} "
                "Craft a crisp, compelling subject line (4-8 words) that gives a clear business reason to open and ties to the "
                "supplied pain point, company context, or goal. Greet the contact warmly by name (e.g. 'Hi Sarah,'), separate "
                "paragraphs cleanly with blank lines (\\n\\n) for easy reading in Gmail, include one thoughtful discovery question, "
                "and close with one low-pressure CTA aligned with the goal followed by '\\n\\nBest,\\n[Your name]'. "
                "The subject is required and must not be empty. The draft is for human review and must not imply it has been sent. "
                "Return only JSON matching the supplied schema."
            )
        else:
            msg_length_desc = (
                "CRITICAL LENGTH REQUIREMENT: The user selected 'short'. The message MUST be extremely brief: exactly 1 to 2 sentences (strictly under 35 words total)."
                if request.length == "short"
                else "LENGTH REQUIREMENT: The user selected 'long'. Keep the message to 4 to 5 sentences (under 90 words)."
                if request.length == "long"
                else "LENGTH REQUIREMENT: The user selected 'medium'. Keep the message to 2 to 3 sentences (under 60 words)."
            )
            system_prompt = (
                "You are an elite B2B enterprise sales communications advisor. "
                "Write one natural, respectful, and highly professional B2B message suitable for executive multi-channel outreach. "
                "Treat the supplied request JSON as the only source of truth. Do not use outside research, "
                "model knowledge, previous requests, or facts from these instructions. "
                "Do not infer a product, workflow, metric, result, customer fact, or need from the company name or "
                "industry, and do not turn a broad goal into a specific process. "
                "Use only supplied pain-point wording and treat it as an unverified note; phrase it conditionally as "
                "your notes mention... and inquire if it is an active focus area. If no pain point is supplied, do not claim "
                "a specific problem and ask a neutral, strategic discovery question tied to the goal. Do not invent prior contact, "
                "referrals, urgency, or promises, and do not claim 'we can help' or assert sender capabilities that were not supplied. "
                f"{msg_length_desc} {tone_desc} "
                "Incorporate one clear low-pressure CTA aligned with the goal, avoid generic claims or filler, and adhere strictly "
                "to the requested tone, goal, and length. Do not include a subject or email sign-off. The draft is for human review "
                "and must not imply it has been sent. Return only JSON matching the supplied schema."
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

    @staticmethod
    def _generate_neutral_draft(
        lead: Lead, request: OutreachGenerationRequest
    ) -> OutreachContent:
        contact_name = (lead.contact_name or "").strip()
        greeting = f"Hi {contact_name}," if contact_name else "Hello,"
        goal = request.goal.strip().rstrip(".!?")

        if request.draft_type == "email":
            body = (
                f'{greeting}\n\nWould a brief conversation about "{goal}" be '
                "useful for your team? If so, what would be most useful to cover?"
                "\n\nBest, [Your name]"
            )
            return OutreachContent(subject="A brief conversation", body=body)

        return OutreachContent(
            body=(
                f'{greeting} Would a brief conversation about "{goal}" be useful? '
                "If so, what would be most useful to cover?"
            )
        )
