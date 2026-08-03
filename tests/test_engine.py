from app.engine import analyze_incident
from app.fixtures import SCENARIOS
from app.models import Artifact, IncidentRequest, RiskLevel


def test_latency_scenario_ranks_retry_amplification_first():
    result = analyze_incident(SCENARIOS["latency"].request)

    assert result.hypotheses[0].title == "Retry amplification after a service change"
    assert result.hypotheses[0].confidence >= 0.80
    assert result.recommendation.risk_level == RiskLevel.APPROVAL_REQUIRED
    assert result.recommendation.approval_required is True


def test_memory_scenario_uses_only_supplied_evidence():
    request = SCENARIOS["memory"].request
    result = analyze_incident(request)

    supplied = {request.description, request.change_event}
    supplied.update(f"{signal.name}: {signal.value}" for signal in request.signals)
    assert all(item.statement in supplied for item in result.evidence)
    assert result.hypotheses[0].title == "Memory leak or unbounded cache growth"


def test_insufficient_evidence_does_not_invent_root_cause():
    request = IncidentRequest(description="The service is behaving unexpectedly today.")
    result = analyze_incident(request)

    assert result.hypotheses[0].confidence < 0.5
    assert "Insufficient evidence" in result.hypotheses[0].title
    assert result.recommendation.risk_level == RiskLevel.READ_ONLY
    assert result.recommendation.approval_required is False


def test_analysis_is_deterministic():
    request = SCENARIOS["database"].request
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
