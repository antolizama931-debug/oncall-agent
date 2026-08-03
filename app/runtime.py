"""Persistent, auditable Agent run state for the OnCall control plane."""

from __future__ import annotations

import secrets
import sqlite3
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from .automation import build_knowledge_candidate, execute_drill, select_runbook
from .models import (
    AgentRun,
    ApprovalRecord,
    ApprovalRequest,
    ExecutionRequest,
    IncidentAnalysis,
    IncidentRequest,
    KnowledgeReviewRequest,
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


def _tool_calls(
    analysis: IncidentAnalysis,
    source_name: str | None,
    investigation_tools: list[ToolCall] | None = None,
) -> list[ToolCall]:
    trace = {step.stage: step for step in analysis.trace}
    observe = trace.get("observe")
    correlate = trace.get("correlate")
    diagnose = trace.get("diagnose")
    gate = trace.get("gate")
    core_calls = [
        ToolCall(
            sequence=1,
            tool="statuspage.read" if source_name else "incident.input",
            purpose="读取公开事故时间线" if source_name else "接收操作员提供的证据",
            status="succeeded",
            output_summary=(
                f"已读取固定可信主机上的 {source_name} 事故回放"
                if source_name
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
    calls = [core_calls[0], *(investigation_tools or []), *core_calls[1:]]
    return [item.model_copy(update={"sequence": index}) for index, item in enumerate(calls, start=1)]


class AgentRunStore:
    """Bounded, thread-safe SQLite-backed run and decision store."""

    def __init__(self, max_runs: int = 100, data_dir: Path | None = None) -> None:
        self.max_runs = max(1, max_runs)
        self._runs: OrderedDict[str, AgentRun] = OrderedDict()
        self._lock = Lock()
        resolved_dir = data_dir or Path("data")
        resolved_dir.mkdir(parents=True, exist_ok=True)
        self.database_path = resolved_dir / "runtime.db"
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_runs (
                run_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._connection.commit()
        self._load()

    def _load(self) -> None:
        rows = self._connection.execute(
            "SELECT payload FROM agent_runs ORDER BY updated_at DESC LIMIT ?", (self.max_runs,)
        ).fetchall()
        for (payload,) in rows:
            try:
                run = AgentRun.model_validate_json(payload)
            except ValueError:
                continue
            self._runs[run.run_id] = run

    def _persist(self, run: AgentRun) -> None:
        self._connection.execute(
            """
            INSERT INTO agent_runs(run_id, session_id, payload, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                session_id = excluded.session_id,
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (run.run_id, run.session_id, run.model_dump_json(), run.updated_at.isoformat()),
        )
        self._connection.execute(
            """
            DELETE FROM agent_runs WHERE run_id NOT IN (
                SELECT run_id FROM agent_runs ORDER BY updated_at DESC LIMIT ?
            )
            """,
            (self.max_runs,),
        )
        self._connection.commit()

    def create(
        self,
        *,
        request: IncidentRequest,
        analysis: IncidentAnalysis,
        session_id: str,
        scenario: Scenario | None = None,
        investigation_tools: list[ToolCall] | None = None,
    ) -> AgentRun:
        now = datetime.now(timezone.utc)
        run_id = f"RUN-{secrets.token_hex(4).upper()}"
        run = AgentRun(
            run_id=run_id,
            session_id=session_id,
            scenario_key=scenario.key if scenario else None,
            title=scenario.title if scenario else request.description[:120],
            display_title=scenario.display_title if scenario else request.description[:120],
            service=request.service,
            severity=request.severity,
            source_name=request.source_name,
            source_url=request.source_url,
            status=_run_status(analysis),
            tool_calls=_tool_calls(
                analysis,
                source_name=scenario.source_name if scenario else request.source_name,
                investigation_tools=investigation_tools,
            ),
            analysis=analysis,
            runbook=select_runbook(analysis),
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._runs[run_id] = run
            self._runs.move_to_end(run_id, last=False)
            while len(self._runs) > self.max_runs:
                self._runs.popitem(last=True)
            self._persist(run)
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
            self._persist(run)
            return run.model_copy(deep=True)

    def execute(self, run_id: str, request: ExecutionRequest) -> AgentRun | None:
        """Run an approved plan through the non-mutating drill connector."""

        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            if run.status != RunStatus.APPROVED:
                raise ValueError("只有已经批准的运行才能进入处置演练")
            if run.runbook is None:
                raise ValueError("该运行没有匹配到可执行 Runbook")
            execution = execute_drill(run.runbook, request.simulated_result)
            run.execution = execution
            run.tool_calls.extend(
                [
                    ToolCall(
                        sequence=len(run.tool_calls) + 1,
                        tool="runbook.execute",
                        purpose="按批准的版本化 Runbook 执行处置",
                        status="succeeded",
                        output_summary=f"已通过{execution.connector}完成 {len(execution.steps)} 个步骤",
                        read_only=False,
                        duration_ms=sum(item.duration_ms for item in execution.steps),
                    ),
                    ToolCall(
                        sequence=len(run.tool_calls) + 2,
                        tool="remediation.validate",
                        purpose="根据恢复条件验证处置结果",
                        status="succeeded" if execution.validation_passed else "failed",
                        output_summary=execution.validation_summary,
                        read_only=True,
                        duration_ms=36,
                    ),
                    ToolCall(
                        sequence=len(run.tool_calls) + 3,
                        tool="knowledge.draft",
                        purpose="生成待审核的事故知识候选",
                        status="succeeded",
                        output_summary="已生成候选复盘，尚未写入正式知识库",
                        read_only=True,
                        duration_ms=22,
                    ),
                ]
            )
            run.status = (
                RunStatus.RECOVERED if execution.validation_passed else RunStatus.ROLLED_BACK
            )
            run.knowledge_candidate = build_knowledge_candidate(
                run_id=run.run_id,
                title=run.display_title or run.title,
                analysis=run.analysis,
                execution=execution,
            )
            run.updated_at = datetime.now(timezone.utc)
            self._runs.move_to_end(run_id, last=False)
            self._persist(run)
            return run.model_copy(deep=True)

    def review_knowledge(
        self, run_id: str, request: KnowledgeReviewRequest
    ) -> AgentRun | None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            if run.knowledge_candidate is None:
                raise ValueError("该运行尚未生成知识候选")
            if run.knowledge_candidate.status != "pending-review":
                raise ValueError("该知识候选已经完成审核")
            run.knowledge_candidate.status = (
                "accepted" if request.decision == "accept" else "rejected"
            )
            run.knowledge_candidate.reviewed_at = datetime.now(timezone.utc)
            run.knowledge_candidate.reviewer = request.reviewer
            run.updated_at = datetime.now(timezone.utc)
            self._persist(run)
            return run.model_copy(deep=True)

    def count(self) -> int:
        with self._lock:
            return len(self._runs)

    def awaiting_count(self) -> int:
        with self._lock:
            return sum(item.status == RunStatus.AWAITING_APPROVAL for item in self._runs.values())

    def recovered_count(self) -> int:
        with self._lock:
            return sum(item.status == RunStatus.RECOVERED for item in self._runs.values())

    def rollback_count(self) -> int:
        with self._lock:
            return sum(item.status == RunStatus.ROLLED_BACK for item in self._runs.values())

    def knowledge_candidate_count(self) -> int:
        with self._lock:
            return sum(item.knowledge_candidate is not None for item in self._runs.values())
