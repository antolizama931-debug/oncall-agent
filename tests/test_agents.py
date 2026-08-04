import asyncio

from app.agents import ConversationAgent, KnowledgeAgent, OperationsAgent
from app.connectors import EnterpriseToolGateway
from app.evidence import SharedEvidenceLayer
from app.knowledge import KnowledgeBaseStore, SessionMemoryStore
from app.models import IncidentRequest, KnowledgeChatRequest, Severity


def build_knowledge_agent() -> tuple[KnowledgeAgent, SharedEvidenceLayer]:
    evidence_layer = SharedEvidenceLayer()
    return KnowledgeAgent(KnowledgeBaseStore(max_documents=3), evidence_layer), evidence_layer


def test_knowledge_agent_returns_shared_evidence():
    agent, _ = build_knowledge_agent()
    agent.add_document(
        "database-runbook.md",
        "数据库连接池耗尽时，检查活动连接数和连接等待时间。".encode("utf-8"),
    )

    result = agent.retrieve("数据库连接池耗尽", top_k=2)

    assert result.citations
    assert result.evidence
    assert result.evidence[0].evidence_id == result.citations[0].citation_id
    assert result.evidence[0].collected_by == "知识库 Agent"


def test_conversation_agent_runs_bounded_react_with_citations():
    knowledge_agent, evidence_layer = build_knowledge_agent()
    knowledge_agent.add_document(
        "payment-runbook.md",
        "支付服务出现 HTTP 503 时，先检查下游依赖和连接池。".encode("utf-8"),
    )
    agent = ConversationAgent(
        knowledge_agent=knowledge_agent,
        memory_store=SessionMemoryStore(max_sessions=2),
        evidence_layer=evidence_layer,
        deepseek_client=None,
        model_name="test-model",
        allow_fallback=True,
    )

    response = asyncio.run(
        agent.answer(KnowledgeChatRequest(question="支付服务 HTTP 503 怎么排查？", session_id="s-1"))
    )

    assert response.citations
    assert response.analysis_mode == "retrieval-unconfigured"
    assert any("Action：调用 knowledge.retrieve" in item for item in response.trace)
    assert any("Observation" in item for item in response.trace)
    assert response.citations[0].citation_id in response.answer


def test_operations_agent_replans_when_initial_knowledge_search_is_empty():
    knowledge_agent, evidence_layer = build_knowledge_agent()
    agent = OperationsAgent(
        knowledge_agent=knowledge_agent,
        evidence_layer=evidence_layer,
        tool_gateway=EnterpriseToolGateway(),
        deepseek_client=None,
        model_name="test-model",
        allow_fallback=True,
    )
    incident = IncidentRequest(
        description="checkout-api 出现未知类型错误，需要进一步调查",
        service="checkout-api",
        severity=Severity.SEV2,
    )

    result = asyncio.run(agent.investigate(incident, use_gateway=False))

    assert result.plan.replan_count == 1
    assert "knowledge.retrieve_broad" in [item.tool for item in result.plan.steps]
    assert [item.sequence for item in result.tool_calls] == list(range(1, len(result.tool_calls) + 1))
    assert result.analysis.trace[0].stage == "plan"
    assert result.analysis.trace[2].stage == "replan"


def test_operations_agent_uses_retrieved_knowledge_as_incident_evidence():
    knowledge_agent, evidence_layer = build_knowledge_agent()
    knowledge_agent.add_document(
        "connection-pool.md",
        "connection pool exhausted 会造成 timeout 和 HTTP 503。".encode("utf-8"),
    )
    agent = OperationsAgent(
        knowledge_agent=knowledge_agent,
        evidence_layer=evidence_layer,
        tool_gateway=EnterpriseToolGateway(),
        deepseek_client=None,
        model_name="test-model",
        allow_fallback=True,
    )
    incident = IncidentRequest(
        description="payment-api reports connection pool exhausted and timeout",
        service="payment-api",
        severity=Severity.SEV2,
    )

    result = asyncio.run(agent.investigate(incident, use_gateway=False))

    assert any(item.name.startswith("knowledge:") for item in result.request.artifacts)
    assert any(item.evidence_type == "knowledge" for item in result.analysis.evidence)
    assert any(item.evidence_id.startswith("K-") for item in result.analysis.evidence)
    valid_ids = {item.evidence_id for item in result.analysis.evidence}
    knowledge_call = next(item for item in result.tool_calls if item.tool == "knowledge.retrieve")
    assert set(knowledge_call.evidence_ids).issubset(valid_ids)
    assert all(
        evidence_id in valid_ids
        for hypothesis in result.analysis.hypotheses
        for evidence_id in hypothesis.supporting_evidence
    )
