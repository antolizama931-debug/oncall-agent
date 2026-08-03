import asyncio
import json

import httpx

from app.deepseek import DeepSeekClient
from app.fixtures import SCENARIOS
from app.models import ChatMessage, KnowledgeCitation, RiskLevel


def test_deepseek_response_is_validated_and_grounded():
    response_content = {
        "summary": "A retry-related latency incident followed a deployment.",
        "hypotheses": [
            {
                "title": "Retry amplification",
                "confidence": 0.83,
                "rationale": "Retry volume and latency increased after the change.",
                "supporting_evidence": ["E-002", "NOT-A-REAL-EVIDENCE-ID"],
                "verification": ["Compare downstream fan-out before and after the deployment."],
            }
        ],
        "suggested_action": "Prepare a reviewed rollback and cap retries.",
        "validation": ["Verify p95 latency and retry rate return to baseline."],
        "rollback": "Restore the deployment only after the retry policy is corrected.",
        "limitations": ["No production system was queried."],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-v4-flash"
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["thinking"] == {"type": "disabled"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(response_content)},
                    }
                ],
                "usage": {
                    "prompt_tokens": 500,
                    "completion_tokens": 180,
                    "total_tokens": 680,
                },
            },
        )

    client = DeepSeekClient(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(client.analyze(SCENARIOS["wikimedia-wfdnbnv00w3r"].request))

    assert result.analysis_mode == "deepseek"
    assert result.model == "deepseek-v4-flash"
    assert result.usage.total_tokens == 680
    assert result.hypotheses[0].supporting_evidence == ["E-002"]
    assert result.recommendation.risk_level == RiskLevel.APPROVAL_REQUIRED


def test_dangerous_model_action_is_blocked():
    response_content = {
        "summary": "Database incident.",
        "hypotheses": [
            {
                "title": "Database corruption",
                "confidence": 0.9,
                "rationale": "The report mentions database errors.",
                "supporting_evidence": ["E-001"],
                "verification": ["Inspect database logs."],
            }
        ],
        "suggested_action": "Drop database production immediately.",
        "validation": ["Check recovery."],
        "rollback": "Restore backup.",
        "limitations": [],
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(response_content)}}],
                "usage": {},
            },
        )

    client = DeepSeekClient(api_key="test-key", transport=httpx.MockTransport(handler))
    result = asyncio.run(client.analyze(SCENARIOS["wikimedia-ncw3k9b4ynz6"].request))

    assert result.recommendation.risk_level == RiskLevel.BLOCKED
    assert "阻断" in result.recommendation.action


def test_knowledge_answer_receives_bounded_memory_and_citation_context():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert "response_format" not in payload
        assert payload["messages"][1]["role"] == "user"
        user_payload = json.loads(payload["messages"][-1]["content"])
        assert user_payload["KNOWLEDGE_CONTEXT"][0]["citation_id"] == "K-TEST-001"
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": "先检查连接池。[K-TEST-001]"}}],
                "usage": {"prompt_tokens": 30, "completion_tokens": 8, "total_tokens": 38},
            },
        )

    client = DeepSeekClient(api_key="test-key", transport=httpx.MockTransport(handler))
    answer, usage = asyncio.run(
        client.answer_question(
            question="应该先检查什么？",
            citations=[
                KnowledgeCitation(
                    citation_id="K-TEST-001",
                    document_id="DOC-TEST",
                    document_name="runbook.md",
                    excerpt="故障时先检查数据库连接池。",
                    relevance=1.0,
                )
            ],
            history=[ChatMessage(role="user", content="这是支付服务。")],
        )
    )
    assert "K-TEST-001" in answer
    assert usage.total_tokens == 38
