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


class RunStatus(str, Enum):
    ANALYZING = "analyzing"
    AWAITING_APPROVAL = "awaiting-approval"
    COMPLETED = "completed"
    APPROVED = "approved"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    EXECUTING = "executing"
    VALIDATING = "validating"
    RECOVERED = "recovered"
    ROLLED_BACK = "rolled-back"
    ESCALATED = "escalated"


class ExecutionMode(str, Enum):
    """How a runbook is allowed to operate.

    The public deployment always uses ``DRY_RUN``. ``CONNECTOR`` is reserved for
    a separately configured enterprise adapter with authentication and RBAC.
    """

    DRY_RUN = "dry-run"
    CONNECTOR = "connector"


class Signal(BaseModel):
    kind: SignalKind
    name: NonEmptyText
    value: NonEmptyText
    timestamp: datetime | None = None
    source: str = "user"
    display_name: str | None = Field(default=None, max_length=160)
    display_value: str | None = Field(default=None, max_length=2000)


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
    # Optional provenance is populated only for imported public incidents. Keeping
    # it in the typed request makes every replay traceable to its original record.
    source_name: str | None = Field(default=None, max_length=120)
    source_url: str | None = Field(default=None, max_length=500)
    source_incident_id: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def limit_total_artifact_size(self):
        if sum(len(item.content) for item in self.artifacts) > 40_000:
            raise ValueError("Total artifact content must not exceed 40,000 characters")
        return self


class Evidence(BaseModel):
    """A normalized observation shared by all three agents.

    ``statement`` keeps backward compatibility with persisted public demo runs.
    The additional fields record provenance without turning a model hypothesis
    into an observation.
    """

    evidence_id: str
    source: str
    statement: str
    relevance: float = Field(ge=0.0, le=1.0)
    observed_at: datetime | None = None
    evidence_type: str = "observation"
    source_url: str | None = None
    collected_by: str = "shared-evidence-layer"
    content_hash: str | None = None


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
    source_name: str
    source_url: str
    source_incident_id: str
    data_mode: str
    fetched_at: datetime
    incident_status: str = "unknown"
    impact: str = "unknown"
    started_at: datetime | None = None
    update_count: int = Field(default=0, ge=0)
    components: list[str] = Field(default_factory=list)
    display_title: str | None = Field(default=None, max_length=300)
    display_summary: str | None = Field(default=None, max_length=1200)


class TokenUsage(BaseModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class AgentRunRequest(BaseModel):
    """Start a run from a sourced scenario or a user-supplied incident."""

    scenario_key: str | None = Field(default=None, max_length=180)
    incident: IncidentRequest | None = None
    session_id: str = Field(default="public-demo", min_length=1, max_length=120)

    @model_validator(mode="after")
    def require_exactly_one_input(self):
        if (self.scenario_key is None) == (self.incident is None):
            raise ValueError("Provide exactly one of scenario_key or incident")
        return self


class ToolCall(BaseModel):
    sequence: int = Field(ge=1)
    tool: str
    purpose: str
    status: str
    output_summary: str
    read_only: bool = True
    duration_ms: int = Field(ge=0)
    evidence_ids: list[str] = Field(default_factory=list)


class AgentPlanStep(BaseModel):
    """One bounded step produced by the operations Agent planner."""

    step_id: str
    tool: str
    purpose: str
    status: str = Field(default="pending", pattern="^(pending|running|succeeded|failed|skipped)$")


class AgentPlan(BaseModel):
    """Observable Plan-Execute-Replan state exposed for replay."""

    goal: str
    steps: list[AgentPlanStep]
    replan_count: int = Field(default=0, ge=0)


class RunbookStep(BaseModel):
    sequence: int = Field(ge=1)
    operation: str
    description: str
    mutating: bool = False


class RunbookPlan(BaseModel):
    runbook_id: str
    name: str
    version: str
    risk_level: RiskLevel
    execution_mode: ExecutionMode = ExecutionMode.DRY_RUN
    auto_executable: bool = False
    steps: list[RunbookStep]
    validation_checks: list[str]
    rollback_steps: list[str]


class ExecutionStepResult(BaseModel):
    sequence: int = Field(ge=1)
    operation: str
    status: str = Field(pattern="^(succeeded|failed|skipped)$")
    output_summary: str
    duration_ms: int = Field(ge=0)


class RemediationExecution(BaseModel):
    execution_id: str
    mode: ExecutionMode
    connector: str
    simulated: bool = True
    status: str = Field(pattern="^(recovered|rolled-back|escalated)$")
    steps: list[ExecutionStepResult]
    validation_passed: bool
    validation_summary: str
    rollback_performed: bool = False
    rollback_summary: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExecutionRequest(BaseModel):
    operator: str = Field(default="public-demo-operator", min_length=2, max_length=120)
    confirmation: str = Field(pattern="^EXECUTE DRY RUN$")
    simulated_result: str = Field(default="success", pattern="^(success|failure)$")


class KnowledgeCandidate(BaseModel):
    candidate_id: str
    title: str
    source_run_id: str
    status: str = Field(default="pending-review", pattern="^(pending-review|accepted|rejected)$")
    summary: str
    verified_facts: list[str]
    root_cause: str
    remediation: str
    validation_result: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reviewed_at: datetime | None = None
    reviewer: str | None = None


class KnowledgeReviewRequest(BaseModel):
    decision: str = Field(pattern="^(accept|reject)$")
    reviewer: str = Field(min_length=2, max_length=120)


class ApprovalRecord(BaseModel):
    decision: str
    operator: str
    note: str | None = None
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    action_executed: bool = False


class ApprovalRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    operator: str = Field(default="public-demo-operator", min_length=2, max_length=120)
    note: str | None = Field(default=None, max_length=500)


class AgentRun(BaseModel):
    run_id: str
    session_id: str
    scenario_key: str | None = None
    title: str
    display_title: str | None = None
    service: str
    severity: Severity
    source_name: str | None = None
    source_url: str | None = None
    status: RunStatus
    tool_calls: list[ToolCall]
    analysis: IncidentAnalysis
    agent_name: str = "运维 Agent"
    plan: AgentPlan | None = None
    runbook: RunbookPlan | None = None
    approval: ApprovalRecord | None = None
    execution: RemediationExecution | None = None
    knowledge_candidate: KnowledgeCandidate | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DashboardSummary(BaseModel):
    incident_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    run_count: int = Field(ge=0)
    awaiting_approval_count: int = Field(ge=0)
    source_name: str
    data_mode: str
    deepseek_configured: bool
    model: str
    recovered_count: int = Field(default=0, ge=0)
    rollback_count: int = Field(default=0, ge=0)
    knowledge_candidate_count: int = Field(default=0, ge=0)


class AlertEventRequest(BaseModel):
    """Normalized enterprise alert accepted from a trusted webhook connector."""

    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=6000)]
    service: str = Field(min_length=1, max_length=120)
    severity: Severity = Severity.UNKNOWN
    environment: str = Field(default="production", max_length=80)
    status: str = Field(default="firing", pattern="^(firing|resolved)$")
    fingerprint: str | None = Field(default=None, max_length=200)
    source: str = Field(default="enterprise-webhook", max_length=120)
    change_event: str | None = Field(default=None, max_length=500)
    signals: list[Signal] = Field(default_factory=list, max_length=40)
    labels: dict[str, str] = Field(default_factory=dict)


class AlertReceipt(BaseModel):
    event_id: str
    fingerprint: str
    duplicated: bool
    occurrences: int = Field(ge=1)
    run_id: str | None = None
    status: str
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class KnowledgeDocument(BaseModel):
    document_id: str
    name: str
    media_type: str
    source_type: str = "用户上传"
    source_url: str | None = None
    namespace: str = "user_uploads"
    organization: str = "用户"
    authority_level: float = Field(default=1.0, ge=0.0, le=1.0)
    applicable_for_action: bool = False
    character_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class KnowledgeStatus(BaseModel):
    document_count: int = Field(ge=0)
    uploaded_document_count: int = Field(default=0, ge=0)
    source_document_count: int = Field(default=0, ge=0)
    chunk_count: int = Field(ge=0)
    supported_types: list[str]
    retriever: str
    storage: str
    embedding_model: str | None = None
    retrieval_mode: str = "词法检索"
    source_types: list[str] = Field(default_factory=list)
    namespaces: list[str] = Field(default_factory=list)
    sync_mode: str = "not-loaded"
    sync_error: str | None = None


class KnowledgeCitation(BaseModel):
    citation_id: str
    document_id: str
    document_name: str
    source_type: str = "用户上传"
    source_url: str | None = None
    namespace: str = "user_uploads"
    organization: str = "用户"
    authority_level: float = Field(default=1.0, ge=0.0, le=1.0)
    applicable_for_action: bool = False
    retrieval_signals: list[str] = Field(default_factory=list)
    excerpt: str
    relevance: float = Field(ge=0.0, le=1.0)


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=12_000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class KnowledgeChatRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=4000)]
    session_id: str = Field(min_length=1, max_length=120)
    top_k: int = Field(default=4, ge=1, le=8)


class KnowledgeChatResponse(BaseModel):
    answer: str
    session_id: str
    citations: list[KnowledgeCitation]
    trace: list[str]
    analysis_mode: str
    model: str | None = None
    usage: TokenUsage | None = None
    memory_turns: int = Field(ge=0)
    memory_summary_active: bool = False
    memory_recent_messages: int = Field(default=0, ge=0)
    memory_clipped: bool = False
