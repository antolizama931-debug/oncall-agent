"""Deterministic incident analysis engine.

This module is intentionally model-independent. It gives the public demo a useful,
reproducible baseline and a stable contract for adding an LLM adapter later. The
engine never invents telemetry: evidence is constructed only from user-provided
fields and signals.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .models import (
    Evidence,
    Hypothesis,
    IncidentAnalysis,
    IncidentRequest,
    Recommendation,
    RiskLevel,
    Severity,
    TraceStep,
)


@dataclass(frozen=True)
class DiagnosticRule:
    title: str
    keywords: tuple[str, ...]
    rationale: str
    verification: tuple[str, ...]
    action: str
    validation: tuple[str, ...]
    rollback: str


RULES: tuple[DiagnosticRule, ...] = (
    DiagnosticRule(
        title="服务变更后出现重试放大",
        keywords=("retry", "503", "deployment", "deploy", "latency", "fan-out"),
        rationale="近期变更与重试增加可能放大下游请求量，并抬高尾部时延。",
        verification=(
            "对比变更前后的重试率与下游请求扇出数量。",
            "在安全环境中关闭重试并回放一条代表性请求。",
        ),
        action="准备经过人工复核的近期变更回滚方案，并临时限制重试次数。",
        validation=("持续观察 p95 时延 10 分钟。", "确认错误率和重试率恢复到基线。"),
        rollback="修正重试策略并完成压力测试后，才能重新启用该变更。",
    ),
    DiagnosticRule(
        title="数据库连接池耗尽",
        keywords=("database", "db", "connection", "pool", "query", "timeout", "lock"),
        rationale="连接池饱和或长时间查询会阻塞新请求，并导致写入超时。",
        verification=(
            "检查活动连接、等待事件和运行时间最长的查询。",
            "核对应用超时是否与连接池饱和时间一致。",
        ),
        action="人工评估是否终止占用最高的查询，并减少非关键数据库流量。",
        validation=("确认连接池利用率降到 80% 以下。", "确认写入时延与超时率恢复。"),
        rollback="若写入错误增加，立即停止干预并恢复原流量策略。",
    ),
    DiagnosticRule(
        title="内存泄漏或缓存无上限增长",
        keywords=("memory", "oom", "oomkilled", "cache", "rss", "heap", "restart"),
        rationale="内存持续单调增长并最终触发 OOM，符合状态泄漏或缓存无上限增长的特征。",
        verification=(
            "关联分析常驻内存、缓存基数和请求量。",
            "对比可疑功能启用前后的堆内存分析结果。",
        ),
        action="通过审批门控关闭可疑缓存功能，并逐步替换工作进程。",
        validation=("确认常驻内存进入稳定平台期。", "确认重启和 OOMKilled 事件停止。"),
        rollback="若关闭功能引发正确性问题，恢复功能开关并继续限制流量。",
    ),
    DiagnosticRule(
        title="网络或下游依赖服务性能下降",
        keywords=("network", "dns", "connection reset", "upstream", "downstream", "packet", "503"),
        rationale="传输故障或异常依赖服务可能表现为请求超时和上游错误。",
        verification=(
            "对比不同可用区和实例的依赖健康状态。",
            "检查故障边界处的 DNS 解析、连接重置和 Trace Span。",
        ),
        action="审批通过后，将少量流量切换到健康的依赖实例。",
        validation=("确认传输错误数量下降。", "对比不同路由的时延和成功率。"),
        rollback="若备用路径性能下降，将流量恢复到原路由。",
    ),
)


def _tokenize(request: IncidentRequest) -> str:
    parts = [request.description, request.service, request.environment, request.change_event or ""]
    parts.extend(f"{signal.kind.value} {signal.name} {signal.value}" for signal in request.signals)
    parts.extend(f"artifact {artifact.name} {artifact.content}" for artifact in request.artifacts)
    return " ".join(parts).lower()


def _make_incident_id(request: IncidentRequest) -> str:
    digest = hashlib.sha256(
        f"{request.service}|{request.description}|{request.change_event}".encode("utf-8")
    ).hexdigest()[:6].upper()
    return f"INC-{digest}"


def _build_evidence(request: IncidentRequest) -> list[Evidence]:
    report_source = "user_report"
    if request.source_name and request.source_incident_id:
        report_source = f"{request.source_name.lower().replace(' ', '_')}:{request.source_incident_id}"
    evidence = [
        Evidence(
            evidence_id="E-001",
            source=report_source,
            statement=request.description,
            relevance=0.72,
        )
    ]
    if request.change_event:
        evidence.append(
            Evidence(
                evidence_id=f"E-{len(evidence) + 1:03d}",
                source="change_event",
                statement=request.change_event,
                relevance=0.84,
            )
        )
    for signal in request.signals:
        evidence.append(
            Evidence(
                evidence_id=f"E-{len(evidence) + 1:03d}",
                source=f"{signal.kind.value}:{signal.source}",
                statement=f"{signal.name}: {signal.value}",
                relevance=0.78,
                observed_at=signal.timestamp,
            )
        )
    for artifact in request.artifacts:
        evidence.append(
            Evidence(
                evidence_id=f"E-{len(evidence) + 1:03d}",
                source=f"artifact:{artifact.name}",
                statement=artifact.content,
                relevance=0.74,
            )
        )
    return evidence


def _score_rule(rule: DiagnosticRule, text: str, evidence_count: int) -> tuple[int, list[str]]:
    matched = [keyword for keyword in rule.keywords if keyword in text]
    # Multiple independent observations increase confidence, but cannot replace a keyword match.
    evidence_bonus = min(max(evidence_count - 1, 0), 4)
    return len(matched) * 3 + evidence_bonus, matched


def _rank_hypotheses(request: IncidentRequest, evidence: list[Evidence]) -> list[Hypothesis]:
    text = _tokenize(request)
    scored: list[tuple[int, DiagnosticRule, list[str]]] = []
    for rule in RULES:
        score, matched = _score_rule(rule, text, len(evidence))
        if matched:
            scored.append((score, rule, matched))
    scored.sort(key=lambda item: item[0], reverse=True)

    if not scored:
        return [
            Hypothesis(
                title="证据不足，无法形成可辩护的根因假设",
                confidence=0.30,
                rationale="当前事故信息缺少具有区分性的遥测数据，无法可靠排序根因。",
                supporting_evidence=[evidence[0].evidence_id],
                verification=[
                    "补充服务错误率、时延、饱和度和近期变更事件。",
                    "补充故障时间窗口内具有代表性的日志或 Trace。",
                ],
            )
        ]

    max_score = max(score for score, _, _ in scored)
    hypotheses: list[Hypothesis] = []
    for score, rule, matched in scored[:3]:
        # Confidence is a calibrated heuristic, not a probability claim.
        confidence = min(0.94, 0.48 + 0.035 * score + 0.02 * len(set(matched)))
        if score < max_score:
            confidence = min(confidence, 0.74)
        supporting = [item.evidence_id for item in evidence if any(
            keyword in item.statement.lower() for keyword in matched
        )]
        hypotheses.append(
            Hypothesis(
                title=rule.title,
                confidence=round(confidence, 2),
                rationale=rule.rationale,
                supporting_evidence=supporting or [evidence[0].evidence_id],
                verification=list(rule.verification),
            )
        )
    return hypotheses


def _build_recommendation(request: IncidentRequest, hypotheses: list[Hypothesis]) -> Recommendation:
    primary = hypotheses[0]
    if primary.confidence < 0.5:
        return Recommendation(
            action="提出生产变更前，先补充只读遥测证据。",
            risk_level=RiskLevel.READ_ONLY,
            approval_required=False,
            validation=["补充指标、日志、Trace 和近期变更后重新运行分析。"],
            rollback="当前没有提出任何生产写操作。",
        )

    rule = next((item for item in RULES if item.title == primary.title), None)
    if rule is None:
        raise RuntimeError("Ranked hypothesis has no matching diagnostic rule")

    # Public users never receive an automatically executable write action.
    risk = RiskLevel.APPROVAL_REQUIRED
    if request.severity == Severity.UNKNOWN:
        risk = RiskLevel.BLOCKED
    return Recommendation(
        action=rule.action,
        risk_level=risk,
        approval_required=True,
        validation=list(rule.validation),
        rollback=rule.rollback,
    )


def analyze_incident(request: IncidentRequest) -> IncidentAnalysis:
    """Run the observable, deterministic analysis pipeline."""
    evidence = _build_evidence(request)
    hypotheses = _rank_hypotheses(request, evidence)
    recommendation = _build_recommendation(request, hypotheses)
    primary = hypotheses[0]
    service = re.sub(r"[^a-zA-Z0-9_.-]", "", request.service) or "unknown-service"

    trace = [
        TraceStep(stage="observe", message=f"已规范化 {len(evidence)} 条证据记录", duration_ms=18),
        TraceStep(stage="correlate", message="已对齐事故报告、信号和变更事件", duration_ms=31),
        TraceStep(stage="diagnose", message=f"已排序 {len(hypotheses)} 个可验证假设", duration_ms=47),
        TraceStep(
            stage="gate",
            message=f"处置建议已映射为 {recommendation.risk_level.value} 风险边界",
            duration_ms=12,
        ),
    ]
    limitations = [
        "置信度是确定性启发式评分，不能解释为经过测量的统计概率。",
        "公开演示没有生产凭据，不能执行修复命令。",
    ]
    if request.source_url:
        limitations.append(
            f"这是公开状态更新的事故回放（{request.source_url}），不包含私有生产遥测。"
        )
    if len(request.signals) < 2:
        limitations.append("当前结构化信号少于两条，需要补充更多遥测。")

    return IncidentAnalysis(
        incident_id=_make_incident_id(request),
        summary=(
            f"{request.severity.value} 事故影响 {service}。"
            f"首要根因假设：{primary.title}（置信度 {primary.confidence:.0%}）。"
        ),
        evidence=evidence,
        hypotheses=hypotheses,
        recommendation=recommendation,
        trace=trace,
        limitations=limitations,
        analysis_mode="deterministic",
    )
