"""Operations Agent: bounded Plan-Execute-Replan incident investigation."""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..connectors import EnterpriseToolGateway
from ..deepseek import DeepSeekClient, DeepSeekError
from ..engine import analyze_incident
from ..evidence import SharedEvidenceLayer
from ..models import (
    AgentPlan,
    AgentPlanStep,
    IncidentAnalysis,
    IncidentRequest,
    ToolCall,
    TraceStep,
)
from .knowledge import KnowledgeAgent, KnowledgeAgentResult


@dataclass(slots=True)
class OperationsAgentResult:
    request: IncidentRequest
    analysis: IncidentAnalysis
    tool_calls: list[ToolCall]
    plan: AgentPlan


class OperationsAgent:
    """Plan, execute registered read tools, and adjust a bounded plan."""

    name = "运维 Agent"
    maximum_steps = 8
    maximum_replans = 2

    def __init__(
        self,
        *,
        knowledge_agent: KnowledgeAgent,
        evidence_layer: SharedEvidenceLayer,
        tool_gateway: EnterpriseToolGateway,
        deepseek_client: DeepSeekClient | None,
        model_name: str,
        allow_fallback: bool,
    ) -> None:
        self.knowledge_agent = knowledge_agent
        self.evidence_layer = evidence_layer
        self.tool_gateway = tool_gateway
        self.deepseek_client = deepseek_client
        self.model_name = model_name
        self.allow_fallback = allow_fallback

    @staticmethod
    def _step(step_id: str, tool: str, purpose: str) -> AgentPlanStep:
        return AgentPlanStep(step_id=step_id, tool=tool, purpose=purpose)

    def _plan(self, request: IncidentRequest, *, use_gateway: bool) -> AgentPlan:
        steps = [
            self._step("P-01", "incident.read", "读取并校验事故输入"),
            self._step("P-02", "knowledge.retrieve", "查询与事故相关的历史记录和处理手册"),
        ]
        if use_gateway:
            steps.append(
                self._step("P-03", "telemetry.collect", "查询企业指标、日志、Trace 和近期变更")
            )
        steps.extend(
            [
                self._step("P-04", "diagnosis.analyze", "根据证据生成可验证的根因假设"),
                self._step("P-05", "evidence.validate", "校验假设引用并输出结论"),
            ]
        )
        return AgentPlan(goal=f"调查 {request.service} 的当前故障", steps=steps)

    @staticmethod
    def _broad_query(request: IncidentRequest) -> str:
        terms = [request.service, request.description]
        terms.extend(signal.name for signal in request.signals[:8])
        if request.change_event:
            terms.append(request.change_event)
        return " ".join(item for item in terms if item)[:4000]

    async def _analyze(self, request: IncidentRequest) -> IncidentAnalysis:
        if self.deepseek_client is not None:
            try:
                return await self.deepseek_client.analyze(request)
            except DeepSeekError:
                if not self.allow_fallback:
                    raise
                result = analyze_incident(request)
                result.analysis_mode = "deterministic-fallback"
                result.model = self.model_name
                result.limitations.append("模型暂时不可用，本次使用确定性规则继续调查。")
                return result
        result = analyze_incident(request)
        result.analysis_mode = "deterministic-unconfigured"
        result.limitations.append("未配置模型，本次使用确定性规则完成调查。")
        return result

    async def investigate(
        self,
        request: IncidentRequest,
        *,
        use_gateway: bool,
    ) -> OperationsAgentResult:
        plan = self._plan(request, use_gateway=use_gateway)
        current = request.model_copy(deep=True)
        calls: list[ToolCall] = []
        analysis: IncidentAnalysis | None = None
        knowledge_result: KnowledgeAgentResult | None = None
        broad_attempted = False
        cursor = 0

        while cursor < len(plan.steps) and cursor < self.maximum_steps:
            step = plan.steps[cursor]
            plan.steps[cursor] = step.model_copy(update={"status": "running"})
            started = time.perf_counter()
            status = "succeeded"
            summary = ""
            evidence_ids: list[str] = []

            try:
                if step.tool == "incident.read":
                    evidence = self.evidence_layer.from_incident(current)
                    evidence_ids = [item.evidence_id for item in evidence]
                    summary = f"已读取事故输入并识别 {len(evidence)} 条初始证据"

                elif step.tool in {"knowledge.retrieve", "knowledge.retrieve_broad"}:
                    query = current.description if step.tool == "knowledge.retrieve" else self._broad_query(current)
                    knowledge_result = self.knowledge_agent.retrieve(query, top_k=4)
                    evidence_ids = [item.evidence_id for item in knowledge_result.evidence]
                    current = self.evidence_layer.attach_knowledge(current, knowledge_result.citations)
                    summary = f"知识库 Agent 返回 {len(knowledge_result.citations)} 个相关片段"
                    broad_attempted = broad_attempted or step.tool == "knowledge.retrieve_broad"

                elif step.tool == "telemetry.collect":
                    if not self.tool_gateway.configured:
                        status = "skipped"
                        summary = "企业工具网关未配置，保留现有证据继续调查"
                    else:
                        current, gateway_calls = await self.tool_gateway.collect(current)
                        for gateway_call in gateway_calls:
                            calls.append(
                                gateway_call.model_copy(
                                    update={
                                        "sequence": len(calls) + 1,
                                        "evidence_ids": [],
                                    }
                                )
                            )
                        succeeded = sum(item.status == "succeeded" for item in gateway_calls)
                        status = "succeeded" if succeeded else "failed"
                        summary = f"企业工具返回 {succeeded}/{len(gateway_calls)} 个成功结果"

                elif step.tool == "diagnosis.analyze":
                    analysis = await self._analyze(current)
                    evidence_ids = [item.evidence_id for item in analysis.evidence]
                    summary = f"生成 {len(analysis.hypotheses)} 个可验证假设"

                elif step.tool == "evidence.validate":
                    if analysis is None:
                        raise RuntimeError("诊断尚未完成")
                    analysis = self.evidence_layer.validate_analysis(analysis)
                    evidence_ids = [
                        evidence_id
                        for item in analysis.hypotheses
                        for evidence_id in item.supporting_evidence
                    ]
                    summary = f"已校验 {len(set(evidence_ids))} 个假设引用"
                else:
                    raise RuntimeError(f"未注册的运维工具：{step.tool}")
            except Exception as exc:
                status = "failed"
                summary = f"步骤失败：{type(exc).__name__}"
                if step.tool in {"diagnosis.analyze", "evidence.validate"}:
                    raise

            duration_ms = max(0, int((time.perf_counter() - started) * 1000))
            calls.append(
                ToolCall(
                    sequence=len(calls) + 1,
                    tool=step.tool,
                    purpose=step.purpose,
                    status=status,
                    output_summary=summary,
                    read_only=True,
                    duration_ms=duration_ms,
                    evidence_ids=list(dict.fromkeys(evidence_ids)),
                )
            )
            plan.steps[cursor] = plan.steps[cursor].model_copy(update={"status": status})

            # Replanner changes the remaining plan only when observations show
            # the original plan is insufficient.
            additions: list[AgentPlanStep] = []
            if (
                step.tool == "knowledge.retrieve"
                and knowledge_result is not None
                and not knowledge_result.citations
                and plan.replan_count < self.maximum_replans
            ):
                additions = [
                    self._step("R-01", "knowledge.retrieve_broad", "扩大关键词范围再次查询知识库")
                ]
            elif (
                step.tool == "diagnosis.analyze"
                and analysis is not None
                and analysis.hypotheses
                and analysis.hypotheses[0].confidence < 0.5
                and not broad_attempted
                and plan.replan_count < self.maximum_replans
            ):
                additions = [
                    self._step("R-02", "knowledge.retrieve_broad", "证据不足，扩大知识检索范围"),
                    self._step("R-03", "diagnosis.analyze", "使用补充证据重新生成根因假设"),
                ]
            if additions:
                plan.steps[cursor + 1:cursor + 1] = additions
                plan.replan_count += 1

            cursor += 1

        if analysis is None:
            analysis = await self._analyze(current)
        analysis = self.evidence_layer.validate_analysis(analysis)
        plan_trace = [
            TraceStep(
                stage="plan",
                message=f"运维 Agent 制定 {len(plan.steps)} 个步骤的调查计划",
                duration_ms=0,
            ),
            TraceStep(
                stage="execute",
                message=f"已执行 {len(calls)} 次受限工具调用",
                duration_ms=sum(item.duration_ms for item in calls),
            ),
            TraceStep(
                stage="replan",
                message=f"Replanner 调整计划 {plan.replan_count} 次",
                duration_ms=0,
            ),
        ]
        analysis = analysis.model_copy(update={"trace": [*plan_trace, *analysis.trace]})
        return OperationsAgentResult(
            request=current,
            analysis=analysis,
            tool_calls=[item.model_copy(update={"sequence": index}) for index, item in enumerate(calls, start=1)],
            plan=plan,
        )

