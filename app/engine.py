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
        title="Retry amplification after a service change",
        keywords=("retry", "503", "deployment", "deploy", "latency", "fan-out"),
        rationale="A recent change and increased retries can multiply downstream work and inflate tail latency.",
        verification=(
            "Compare retry rate and downstream request fan-out before and after the change.",
            "Replay one request with retries disabled in a safe environment.",
        ),
        action="Prepare a reviewed rollback of the recent service change and temporarily cap retries.",
        validation=("Track p95 latency for 10 minutes.", "Confirm error and retry rates return to baseline."),
        rollback="Re-enable the change only after the retry policy is corrected and load-tested.",
    ),
    DiagnosticRule(
        title="Database connection-pool exhaustion",
        keywords=("database", "db", "connection", "pool", "query", "timeout", "lock"),
        rationale="Pool saturation or a long-running query can block new requests and cause write timeouts.",
        verification=(
            "Inspect active connections, wait events, and the longest-running queries.",
            "Check whether application timeouts align with pool saturation.",
        ),
        action="Review cancellation of the dominant query and reduce non-critical database traffic.",
        validation=("Confirm pool utilization falls below 80%.", "Verify write latency and timeout rate recover."),
        rollback="Stop the intervention if write errors increase; restore the previous traffic policy.",
    ),
    DiagnosticRule(
        title="Memory leak or unbounded cache growth",
        keywords=("memory", "oom", "oomkilled", "cache", "rss", "heap", "restart"),
        rationale="Monotonic memory growth followed by OOM termination is consistent with leaked or unbounded state.",
        verification=(
            "Correlate resident memory with cache cardinality and request volume.",
            "Compare heap profiles before and after the suspected feature was enabled.",
        ),
        action="Disable the suspected cache feature behind an approval gate and replace workers gradually.",
        validation=("Confirm resident memory plateaus.", "Verify restart and OOMKilled events stop."),
        rollback="Restore the flag if disabling it causes correctness failures; retain reduced traffic.",
    ),
    DiagnosticRule(
        title="Network or downstream dependency degradation",
        keywords=("network", "dns", "connection reset", "upstream", "downstream", "packet", "503"),
        rationale="Transport failures or an unhealthy dependency can surface as timeouts and upstream errors.",
        verification=(
            "Compare dependency health across zones and instances.",
            "Inspect DNS resolution, connection resets, and trace spans at the failure boundary.",
        ),
        action="Shift a limited share of traffic to a healthy dependency instance after approval.",
        validation=("Confirm transport errors decline.", "Compare latency and success rate across routes."),
        rollback="Return traffic to the original route if the alternate path degrades.",
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
    evidence = [
        Evidence(
            evidence_id="E-001",
            source="user_report",
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
                title="Insufficient evidence for a defensible root-cause hypothesis",
                confidence=0.30,
                rationale="The report does not contain enough discriminating telemetry to rank a cause.",
                supporting_evidence=[evidence[0].evidence_id],
                verification=[
                    "Collect service error rate, latency, saturation, and recent change events.",
                    "Add representative logs or traces from the failure window.",
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
            action="Collect additional read-only telemetry before proposing a production change.",
            risk_level=RiskLevel.READ_ONLY,
            approval_required=False,
            validation=["Re-run analysis after adding metrics, logs, traces, and recent changes."],
            rollback="No production mutation is proposed.",
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
        TraceStep(stage="observe", message=f"Normalized {len(evidence)} evidence records", duration_ms=18),
        TraceStep(stage="correlate", message="Aligned report, signals, and change events", duration_ms=31),
        TraceStep(stage="diagnose", message=f"Ranked {len(hypotheses)} testable hypotheses", duration_ms=47),
        TraceStep(
            stage="gate",
            message=f"Mapped recommendation to {recommendation.risk_level.value}",
            duration_ms=12,
        ),
    ]
    limitations = [
        "Confidence is a deterministic heuristic and must not be interpreted as a measured probability.",
        "The public demo has no production credentials and cannot execute remediation commands.",
    ]
    if len(request.signals) < 2:
        limitations.append("Fewer than two structured signals were supplied; collect more telemetry.")

    return IncidentAnalysis(
        incident_id=_make_incident_id(request),
        summary=(
            f"{request.severity.value} incident affecting {service}. "
            f"Primary hypothesis: {primary.title} ({primary.confidence:.0%} confidence)."
        ),
        evidence=evidence,
        hypotheses=hypotheses,
        recommendation=recommendation,
        trace=trace,
        limitations=limitations,
        analysis_mode="deterministic",
    )
