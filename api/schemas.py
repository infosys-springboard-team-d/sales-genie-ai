from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class LeadStatus(str, Enum):
    NEW = "New"
    CONTACTED = "Contacted"
    QUALIFIED = "Qualified"
    PROPOSAL = "Proposal"
    WON = "Won"
    LOST = "Lost"


class LeadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(min_length=1, max_length=255)
    industry: str | None = Field(default=None, max_length=120)
    contact_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=64)
    lead_status: LeadStatus = LeadStatus.NEW

    @field_validator("company_name", "industry", "contact_name", "email", "phone", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("company_name")
    @classmethod
    def company_name_is_required(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("company_name is required.")
        return value

    @field_validator("email")
    @classmethod
    def email_is_valid(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Must be a valid email address.")
        return value


class CsvLeadInput(LeadCreate):
    lead_status: LeadStatus = LeadStatus.NEW

    @field_validator("lead_status", mode="before")
    @classmethod
    def blank_status_uses_default(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return LeadStatus.NEW
        return value.strip() if isinstance(value, str) else value


class LeadPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str | None = Field(default=None, min_length=1, max_length=255)
    industry: str | None = Field(default=None, max_length=120)
    contact_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=64)

    @field_validator("company_name", "industry", "contact_name", "email", "phone", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("email")
    @classmethod
    def email_is_valid(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Must be a valid email address.")
        return value


class LeadStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_status: LeadStatus


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lead_id: int
    company_name: str
    industry: str | None
    contact_name: str | None
    email: str | None
    phone: str | None
    lead_status: LeadStatus
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class LeadPage(BaseModel):
    items: list[LeadOut]
    page: int
    page_size: int
    total: int


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: str | None = Field(default=None, max_length=5000)

    @field_validator("context", mode="before")
    @classmethod
    def normalize_context(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class QualificationOut(BaseModel):
    score: int
    rationale: str
    factors: dict[str, int]


class AnalysisOut(BaseModel):
    analysis_id: int
    lead_id: int
    summary: str
    potential_needs: list[str]
    opportunities: list[str]
    qualification: QualificationOut
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def timestamp_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class ImportRowIssue(BaseModel):
    row: int
    code: str
    message: str


class ImportResult(BaseModel):
    created: int
    duplicates: int
    rejected: int
    committed: bool
    row_errors: list[ImportRowIssue]
    duplicate_rows: list[int]
    rolled_back_rows: list[int]
