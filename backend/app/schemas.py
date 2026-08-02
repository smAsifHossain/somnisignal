from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


DISCLAIMER = (
    "This experimental result is not a diagnosis and cannot rule sleep apnea in or out. "
    "Discuss symptoms and appropriate polysomnography or home sleep-apnea testing with a qualified clinician."
)


class JobState(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class ScreeningOutcome(StrEnum):
    elevated_risk = "elevated_risk"
    low_risk = "low_risk"
    inconclusive = "inconclusive"


class SignalQuality(StrEnum):
    pass_ = "pass"
    warn = "warn"
    fail = "fail"


class ScreeningResult(BaseModel):
    outcome: ScreeningOutcome
    risk_score: float | None = Field(default=None, ge=0.0, le=1.0)
    analyzed_minutes: int = Field(ge=0)
    estimated_apnea_minutes: int | None = Field(default=None, ge=0)
    signal_quality: SignalQuality
    reasons: list[str] = Field(default_factory=list)
    model_version: str
    disclaimer: str = DISCLAIMER


class JobAccepted(BaseModel):
    job_id: str
    status: JobState
    status_url: str
    expires_in_seconds: int


class JobResponse(BaseModel):
    job_id: str
    status: JobState
    created_at: datetime
    expires_at: datetime
    result: ScreeningResult | None = None
    error: str | None = None


class DemoPredictionRequest(BaseModel):
    record_id: str = Field(pattern=r"^(a01|b01|c01)$")
    adult_confirmed: bool
    research_consent: bool


class HealthResponse(BaseModel):
    status: str
    model_ready: bool
    model_version: str | None
    model_release_gate_passed: bool
    public_uploads_enabled: bool
    research_demo_uploads_enabled: bool
