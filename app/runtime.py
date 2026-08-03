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


def _analysis_mode_label(mode: str) -> str:
    return {
        "deepseek": "DeepSeek 模型分析",
        "deterministic": "确定性规则分析",
        "deterministic-fallback": "确定性降级分析",
        "deterministic-unconfigured": "未配置模型时的确定性分析",
    }.get(mode, mode)


def _risk_label(risk: RiskLevel) -> str:
    return {
        RiskLevel.READ_ONLY: "只读建议",
        RiskLevel.APPROVAL_REQUIRED: "需要人工审批",
        RiskLevel.BLOCKED: "已阻断",
    }[risk]


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
            purpose="读取公开事故时间线" if sourced else "接收操作员提供的证据",
            status="succeeded",
            output_summary=(
                "已读取固定可信主机上的 GitHub Status 事故回放"
                if sourced
                else "已校验操作员提交的事故字段"
            ),
            duration_ms=observe.duration_ms if observe else 0,
        ),
        ToolCall(
            sequence=2,
            tool="evidence.normalize",
            purpose="分离观察事实与根因假设",
            status="succeeded",
            output_summary=f"已生成 {len(analysis.evidence)} 条结构化证据记录",
            duration_ms=correlate.duration_ms if correlate else 0,
        ),
        ToolCall(
            sequence=3,
            tool="diagnosis.rank",
            purpose="生成并排序可验证的根因假设",
            status="succeeded",
            output_summary=f"已通过{_analysis_mode_label(analysis.analysis_mode)}排序 {len(analysis.hypotheses)} 个假设",
            duration_ms=diagnose.duration_ms if diagnose else 0,
        ),
        ToolCall(
            sequence=4,
            tool="citations.validate",
            purpose="拒绝没有证据支持的引用",
            status="succeeded",
            output_summary="已根据已知证据 ID 校验假设引用",
            duration_ms=4,
        ),
        ToolCall(
            sequence=5,
            tool="policy.gate",
            purpose="将处置建议风险映射到执行边界",
            status="succeeded",
            output_summary=f"风险决策：{_risk_label(analysis.recommendation.risk_level)}",
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
                raise ValueError("该运行记录当前不处于待审批状态")
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
