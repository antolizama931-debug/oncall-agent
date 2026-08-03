"""Policy-constrained runbook planning and deterministic drill execution.

This module intentionally does not contain shell, Kubernetes, cloud, or database
clients. The public application can therefore demonstrate the complete control
loop without acquiring production credentials or pretending that a real change
was made. Enterprise connectors can implement the same contract behind RBAC,
change windows, canaries, and an explicit deployment-specific allow-list.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from .models import (
    ExecutionMode,
    ExecutionStepResult,
    IncidentAnalysis,
    KnowledgeCandidate,
    RemediationExecution,
    RiskLevel,
    RunbookPlan,
    RunbookStep,
)


@dataclass(frozen=True)
class RunbookDefinition:
    runbook_id: str
    name: str
    match_terms: tuple[str, ...]
    risk_level: RiskLevel
    steps: tuple[tuple[str, str, bool], ...]
    validation_checks: tuple[str, ...]
    rollback_steps: tuple[str, ...]


RUNBOOKS: tuple[RunbookDefinition, ...] = (
    RunbookDefinition(
        runbook_id="RB-DEPLOYMENT-ROLLBACK",
        name="近期变更回滚演练",
        match_terms=("变更", "重试", "发布", "deployment", "retry"),
        risk_level=RiskLevel.APPROVAL_REQUIRED,
        steps=(
            ("change.read", "读取最近一次发布版本和变更窗口", False),
            ("traffic.freeze", "冻结继续放量，保留当前流量快照", True),
            ("deployment.rollback", "回滚到最近一个已验证版本", True),
        ),
        validation_checks=("错误率恢复到事故前基线", "p95 时延连续两个观察窗口恢复", "重试率没有继续放大"),
        rollback_steps=("停止回滚任务", "恢复事故发生前的流量策略", "升级人工并保留证据快照"),
    ),
    RunbookDefinition(
        runbook_id="RB-DATABASE-PRESSURE",
        name="数据库连接压力缓解演练",
        match_terms=("数据库", "连接池", "查询", "database", "connection", "timeout"),
        risk_level=RiskLevel.APPROVAL_REQUIRED,
        steps=(
            ("database.observe", "读取连接池、等待事件和慢查询摘要", False),
            ("traffic.limit", "降低非关键请求进入数据库的速率", True),
            ("query.quarantine", "隔离已批准的异常查询来源", True),
        ),
        validation_checks=("连接池利用率降到策略阈值以下", "写入超时率恢复", "没有产生新的数据一致性错误"),
        rollback_steps=("撤销临时限流", "恢复原请求策略", "升级数据库值班人员"),
    ),
    RunbookDefinition(
        runbook_id="RB-STATELESS-RECYCLE",
        name="无状态工作负载滚动替换演练",
        match_terms=("内存", "OOM", "缓存", "重启", "memory", "cache"),
        risk_level=RiskLevel.APPROVAL_REQUIRED,
        steps=(
            ("workload.observe", "读取实例内存、重启次数和就绪状态", False),
            ("feature.guard", "限制可疑缓存或高内存功能", True),
            ("workload.recycle", "按最小批次滚动替换无状态实例", True),
        ),
        validation_checks=("内存进入稳定平台期", "健康实例比例满足服务目标", "OOMKilled 事件停止增长"),
        rollback_steps=("停止滚动替换", "恢复功能开关", "扩容并升级人工处理"),
    ),
    RunbookDefinition(
        runbook_id="RB-DEPENDENCY-DEGRADE",
        name="下游依赖降级演练",
        match_terms=("下游", "依赖", "第三方", "upstream", "dependency", "5xx"),
        risk_level=RiskLevel.APPROVAL_REQUIRED,
        steps=(
            ("dependency.observe", "读取依赖健康状态、Trace 和失败比例", False),
            ("circuit.break", "为异常依赖启用已批准的熔断策略", True),
            ("fallback.enable", "启用经过验证的降级返回路径", True),
        ),
        validation_checks=("入口错误率下降", "依赖调用量符合熔断策略", "核心业务请求保持可用"),
        rollback_steps=("关闭临时降级路径", "恢复原依赖策略", "升级服务负责人"),
    ),
)


def select_runbook(analysis: IncidentAnalysis) -> RunbookPlan | None:
    """Select a versioned runbook from the primary hypothesis.

    Selection is deterministic and inspectable. It is not an authorization
    decision: the public runtime always returns ``auto_executable=False``.
    """

    if not analysis.hypotheses:
        return None
    hypothesis = analysis.hypotheses[0]
    haystack = f"{hypothesis.title} {hypothesis.rationale}".lower()
    definition = max(
        RUNBOOKS,
        key=lambda candidate: sum(term.lower() in haystack for term in candidate.match_terms),
    )
    if not any(term.lower() in haystack for term in definition.match_terms):
        return None
    return RunbookPlan(
        runbook_id=definition.runbook_id,
        name=definition.name,
        version="1.0.0",
        risk_level=definition.risk_level,
        execution_mode=ExecutionMode.DRY_RUN,
        auto_executable=False,
        steps=[
            RunbookStep(sequence=index, operation=operation, description=description, mutating=mutating)
            for index, (operation, description, mutating) in enumerate(definition.steps, start=1)
        ],
        validation_checks=list(definition.validation_checks),
        rollback_steps=list(definition.rollback_steps),
    )


def execute_drill(plan: RunbookPlan, simulated_result: str) -> RemediationExecution:
    """Execute a deterministic, non-mutating remediation drill.

    ``simulated_result`` exists so tests and demonstrations can exercise both the
    recovery and rollback branches. No external command is invoked.
    """

    started_at = datetime.now(timezone.utc)
    results: list[ExecutionStepResult] = []
    for step in plan.steps:
        results.append(
            ExecutionStepResult(
                sequence=step.sequence,
                operation=step.operation,
                status="succeeded",
                output_summary=(
                    f"演练完成：{step.description}。未连接生产系统，未产生真实变更。"
                ),
                duration_ms=18 + step.sequence * 7,
            )
        )

    validation_passed = simulated_result == "success"
    if validation_passed:
        status = "recovered"
        validation_summary = "演练指标满足全部恢复条件，闭环进入已恢复状态。"
        rollback_performed = False
        rollback_summary = None
    else:
        status = "rolled-back"
        validation_summary = "演练指标未满足恢复条件，策略引擎停止继续执行。"
        rollback_performed = True
        rollback_summary = "已演练回滚步骤，并将事故升级给人工值班人员。"

    return RemediationExecution(
        execution_id=f"EXEC-{secrets.token_hex(4).upper()}",
        mode=ExecutionMode.DRY_RUN,
        connector="内置安全演练连接器",
        simulated=True,
        status=status,
        steps=results,
        validation_passed=validation_passed,
        validation_summary=validation_summary,
        rollback_performed=rollback_performed,
        rollback_summary=rollback_summary,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
    )


def build_knowledge_candidate(
    *, run_id: str, title: str, analysis: IncidentAnalysis, execution: RemediationExecution
) -> KnowledgeCandidate:
    """Create a reviewable post-incident record; never publish it automatically."""

    hypothesis = analysis.hypotheses[0]
    facts = [item.statement for item in analysis.evidence[:8]]
    return KnowledgeCandidate(
        candidate_id=f"KB-{secrets.token_hex(4).upper()}",
        title=f"{title}：处置记录候选",
        source_run_id=run_id,
        summary=f"Agent 使用 {len(analysis.evidence)} 条证据完成调查，并执行了{execution.connector}。",
        verified_facts=facts,
        root_cause=f"候选根因：{hypothesis.title}（置信度 {hypothesis.confidence:.0%}，仍需审核）",
        remediation=analysis.recommendation.action,
        validation_result=execution.validation_summary,
    )
