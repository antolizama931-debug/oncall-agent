"""Auditable Agent run/session state for the public OnCall control plane.

The store is deliberately process-local: it records demo decisions without adding
a database or pretending to persist production incident state. Every tool call in
a run corresponds to a real backend stage and no remediation is executed.
"""

from __future__ import annotations

import secrets
from collections import OrderedDict
from datetime import datetime, timezone
from threading import Lock

from .models import (
    AgentRun,
    ApprovalRecord,
    ApprovalRequest,
    IncidentAnalysis,
    IncidentRequest,
    RiskLevel,
    RunStatus,
    Scenario,
    ToolCall,
)


def _run_status(analysis: IncidentAnalysis) -> RunStatus:
    recommendation = analysis.recommendation
    if recommendation.risk_level == RiskLevel.BLOCKED:
        return RunStatus.BLOCKED
    if recommendation.approval_required:
        return RunStatus.AWAITING_APPROVAL
    return RunStatus.COMPLETED


def _tool_calls(analysis: IncidentAnalysis, sourced: bool) -> list[ToolCall]:
    trace = {step.stage: step for step in analysis.trace}
    observe = trace.get("observe")
    correlate = trace.get("correlate")
    diagnose = trace.get("diagnose")
    gate = trace.get("gate")
    return [
        ToolCall(
            sequence=1,
            tool="github_status.read" if sourced else "incident.input",
            purpose="Load public incident timeline" if sourced else "Accept operator evidence",
            status="succeeded",
            output_summary=(
                "Loaded a fixed-host GitHub Status replay"
                if sourced
                else "Validated operator-supplied incident fields"
            ),
            duration_ms=observe.duration_ms if observe else 0,
        ),
        ToolCall(
            sequence=2,
            tool="evidence.normalize",
            purpose="Separate observations from hypotheses",
            status="succeeded",
            output_summary=f"Produced {len(analysis.evidence)} typed evidence records",
            duration_ms=correlate.duration_ms if correlate else 0,
        ),
        ToolCall(
            sequence=3,
            tool="diagnosis.rank",
            purpose="Generate and rank testable hypotheses",
            status="succeeded",
            output_summary=f"Ranked {len(analysis.hypotheses)} hypotheses via {analysis.analysis_mode}",
            duration_ms=diagnose.duration_ms if diagnose else 0,
        ),
        ToolCall(
            sequence=4,
            tool="citations.validate",
            purpose="Reject unsupported evidence references",
            status="succeeded",
            output_summary="Validated hypothesis citations against known evidence IDs",
            duration_ms=4,
        ),
        ToolCall(
            sequence=5,
            tool="policy.gate",
            purpose="Map recommendation risk to an execution boundary",
            status="succeeded",
            output_summary=f"Decision: {analysis.recommendation.risk_level.value}",
            duration_ms=gate.duration_ms if gate else 0,
        ),
    ]


class AgentRunStore:
    """Bounded, thread-safe demo run store."""

    def __init__(self, max_runs: int = 100) -> None:
        self.max_runs = max(1, max_runs)
        self._runs: OrderedDict[str, AgentRun] = OrderedDict()
        self._lock = Lock()

    def create(
        self,
        *,
        request: IncidentRequest,
        analysis: IncidentAnalysis,
        session_id: str,
        scenario: Scenario | None = None,
    ) -> AgentRun:
        now = datetime.now(timezone.utc)
        run_id = f"RUN-{secrets.token_hex(4).upper()}"
        run = AgentRun(
            run_id=run_id,
            session_id=session_id,
            scenario_key=scenario.key if scenario else None,
            title=scenario.title if scenario else request.description[:120],
            service=request.service,
            severity=request.severity,
            source_name=request.source_name,
            source_url=request.source_url,
            status=_run_status(analysis),
            tool_calls=_tool_calls(analysis, sourced=scenario is not None),
            analysis=analysis,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._runs[run_id] = run
            self._runs.move_to_end(run_id, last=False)
            while len(self._runs) > self.max_runs:
                self._runs.popitem(last=True)
        return run.model_copy(deep=True)

    def get(self, run_id: str) -> AgentRun | None:
        with self._lock:
            run = self._runs.get(run_id)
            return run.model_copy(deep=True) if run else None

    def list(self, session_id: str | None = None) -> list[AgentRun]:
        with self._lock:
            values = list(self._runs.values())
            if session_id:
                values = [item for item in values if item.session_id == session_id]
            return [item.model_copy(deep=True) for item in values]

    def decide(self, run_id: str, request: ApprovalRequest) -> AgentRun | None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            if run.status != RunStatus.AWAITING_APPROVAL:
                raise ValueError("Run is not awaiting approval")
            run.approval = ApprovalRecord(
                decision=request.decision,
                operator=request.operator,
                note=request.note,
                # The public control plane records decisions but never executes actions.
                action_executed=False,
            )
            run.status = RunStatus.APPROVED if request.decision == "approve" else RunStatus.REJECTED
            run.updated_at = datetime.now(timezone.utc)
            return run.model_copy(deep=True)

    def count(self) -> int:
        with self._lock:
            return len(self._runs)

    def awaiting_count(self) -> int:
        with self._lock:
            return sum(item.status == RunStatus.AWAITING_APPROVAL for item in self._runs.values())
