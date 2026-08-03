"""Typed API contracts for incident analysis.

The contracts deliberately separate observations, hypotheses, and actions. This
prevents an unverified model statement from being presented as telemetry evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Severity(str, Enum):
    SEV1 = "SEV-1"
    SEV2 = "SEV-2"
    SEV3 = "SEV-3"
    UNKNOWN = "UNKNOWN"


class SignalKind(str, Enum):
    METRIC = "metric"
    LOG = "log"
    TRACE = "trace"
    CHANGE = "change"
    ALERT = "alert"


class RiskLevel(str, Enum):
    READ_ONLY = "read-only"
    APPROVAL_REQUIRED = "approval-required"
    BLOCKED = "blocked"


class Signal(BaseModel):
    kind: SignalKind
    name: NonEmptyText
    value: NonEmptyText
    timestamp: datetime | None = None
    source: str = "user"


class Artifact(BaseModel):
    """User-supplied text artifact such as a log excerpt or metric snapshot."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)]
    media_type: str = Field(default="text/plain", max_length=100)


class IncidentRequest(BaseModel):
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=6000)]
    service: str = Field(default="unknown-service", max_length=120)
    severity: Severity = Severity.UNKNOWN
    environment: str = Field(default="production", max_length=80)
    change_event: str | None = Field(default=None, max_length=500)
    signals: list[Signal] = Field(default_factory=list, max_length=40)
    artifacts: list[Artifact] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def limit_total_artifact_size(self):
        if sum(len(item.content) for item in self.artifacts) > 40_000:
            raise ValueError("Total artifact content must not exceed 40,000 characters")
        return self


class Evidence(BaseModel):
    evidence_id: str
    source: str
    statement: str
    relevance: float = Field(ge=0.0, le=1.0)
    observed_at: datetime | None = None


class Hypothesis(BaseModel):
    title: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    supporting_evidence: list[str]
    verification: list[str]


class Recommendation(BaseModel):
    action: str
    risk_level: RiskLevel
    approval_required: bool
    validation: list[str]
    rollback: str


class TraceStep(BaseModel):
    stage: str
    message: str
    duration_ms: int = Field(ge=0)


class IncidentAnalysis(BaseModel):
    incident_id: str
    summary: str
    evidence: list[Evidence]
    hypotheses: list[Hypothesis]
    recommendation: Recommendation
    trace: list[TraceStep]
    limitations: list[str]
    analysis_mode: str = "deterministic"
    model: str | None = None
    usage: "TokenUsage | None" = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Scenario(BaseModel):
    key: str
    title: str
    subtitle: str
    request: IncidentRequest


class TokenUsage(BaseModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
