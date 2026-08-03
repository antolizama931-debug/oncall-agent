from app.engine import analyze_incident
from app.models import Artifact, IncidentRequest, RiskLevel, Severity, Signal, SignalKind


def latency_request() -> IncidentRequest:
    """Controlled unit-test input; public demo data lives in app.real_data."""
    return IncidentRequest(
        description=(
            "Checkout p95 latency increased after deployment with HTTP 503 errors and retries."
        ),
        service="payment-api",
        severity=Severity.SEV1,
        change_event="deploy completed before the latency increase",
        signals=[
            Signal(kind=SignalKind.METRIC, name="retry_rate", value="increased"),
            Signal(kind=SignalKind.LOG, name="upstream", value="HTTP 503"),
        ],
    )


def test_latency_scenario_ranks_retry_amplification_first():
    result = analyze_incident(latency_request())

    assert result.hypotheses[0].title == "服务变更后出现重试放大"
    assert result.hypotheses[0].confidence >= 0.80
    assert result.recommendation.risk_level == RiskLevel.APPROVAL_REQUIRED
    assert result.recommendation.approval_required is True


def test_memory_scenario_uses_only_supplied_evidence():
    request = IncidentRequest(
        description="Workers restart after memory grows to the container limit with OOMKilled.",
        service="search-worker",
        severity=Severity.SEV2,
        change_event="cache feature enabled before memory growth",
        signals=[Signal(kind=SignalKind.METRIC, name="rss", value="monotonic growth")],
    )
    result = analyze_incident(request)

    supplied = {request.description, request.change_event}
    supplied.update(f"{signal.name}: {signal.value}" for signal in request.signals)
    assert all(item.statement in supplied for item in result.evidence)
    assert result.hypotheses[0].title == "内存泄漏或缓存无上限增长"


def test_insufficient_evidence_does_not_invent_root_cause():
    request = IncidentRequest(description="The service is behaving unexpectedly today.")
    result = analyze_incident(request)

    assert result.hypotheses[0].confidence < 0.5
    assert "证据不足" in result.hypotheses[0].title
    assert result.recommendation.risk_level == RiskLevel.READ_ONLY
    assert result.recommendation.approval_required is False


def test_analysis_is_deterministic():
    request = IncidentRequest(
        description="Database writes timeout because the connection pool is full.",
        service="orders-api",
        severity=Severity.SEV2,
        signals=[Signal(kind=SignalKind.METRIC, name="db.pool", value="100%")],
    )
    first = analyze_incident(request)
    second = analyze_incident(request)

    assert first.incident_id == second.incident_id
    assert first.hypotheses == second.hypotheses
    assert first.recommendation == second.recommendation


def test_user_artifact_becomes_explicit_evidence():
    request = IncidentRequest(
        description="The checkout service returns errors after a deployment.",
        artifacts=[Artifact(name="application.log", content="HTTP 503 retry exhausted")],
    )
    result = analyze_incident(request)

    assert any(item.source == "artifact:application.log" for item in result.evidence)
    assert any(item.statement == "HTTP 503 retry exhausted" for item in result.evidence)
