import asyncio
import os
import tempfile

import httpx

# Tests must never inherit a developer's real model credential from .env. An
# explicitly present empty value prevents load_dotenv() from loading the key.
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["ONCALL_DATA_DIR"] = tempfile.mkdtemp(prefix="oncall-agent-tests-")

from app.main import app, daily_usage, request_windows, status_client
import app.main as main_module
from app.real_data import WIKIMEDIA_STATUS_INCIDENTS


async def request(method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def configure_status_mock() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"incidents": WIKIMEDIA_STATUS_INCIDENTS})

    status_client.transport = httpx.MockTransport(handler)
    status_client._cached = None


def reset_rate_limits() -> None:
    """Keep tests independent from the public-demo request budget."""
    request_windows.clear()
    daily_usage.clear()


def test_health_endpoint():
    response = asyncio.run(request("GET", "/api/health"))
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["deepseek_configured"] is False


def test_scenario_can_be_analyzed_end_to_end():
    reset_rate_limits()
    configure_status_mock()
    scenario_list_response = asyncio.run(request("GET", "/api/scenarios"))
    assert scenario_list_response.status_code == 200
    scenario = scenario_list_response.json()[0]

    response = asyncio.run(
        request("POST", "/api/analyze", json=scenario["request"])
    )
    assert response.status_code == 200
    body = response.json()
    assert body["analysis_mode"] == "deterministic-unconfigured"
    assert body["evidence"][0]["source"].startswith("wikimedia_status:")
    assert body["hypotheses"][0]["confidence"] >= 0.30
    assert body["recommendation"]["risk_level"] in {"read-only", "approval-required"}


def test_scenarios_expose_verifiable_provenance():
    configure_status_mock()
    response = asyncio.run(request("GET", "/api/scenarios"))
    assert response.status_code == 200
    scenario = response.json()[0]
    assert scenario["source_name"] == "Wikimedia Status"
    assert scenario["source_url"].startswith("https://www.wikimediastatus.net/incidents/")
    assert scenario["data_mode"] in {"live", "verified-snapshot"}
    assert scenario["display_title"]
    assert scenario["display_summary"]
    assert scenario["request"]["signals"][0]["display_name"].startswith("第 ")


def test_invalid_short_description_is_rejected():
    reset_rate_limits()
    response = asyncio.run(request("POST", "/api/analyze", json={"description": "short"}))
    assert response.status_code == 422


def test_agent_run_records_tools_and_requires_non_executing_approval():
    reset_rate_limits()
    configure_status_mock()
    scenarios = asyncio.run(request("GET", "/api/scenarios")).json()
    session_id = "test-auditable-agent-session"

    created = asyncio.run(
        request(
            "POST",
            "/api/runs",
            json={"scenario_key": scenarios[1]["key"], "session_id": session_id},
        )
    )
    assert created.status_code == 201
    run = created.json()
    assert run["status"] == "awaiting-approval"
    assert run["display_title"]
    assert [item["tool"] for item in run["tool_calls"]] == [
        "statuspage.read",
        "evidence.normalize",
        "diagnosis.rank",
        "citations.validate",
        "policy.gate",
    ]
    assert all(item["read_only"] is True for item in run["tool_calls"])

    listed = asyncio.run(request("GET", f"/api/runs?session_id={session_id}"))
    assert listed.status_code == 200
    assert listed.json()[0]["run_id"] == run["run_id"]

    decided = asyncio.run(
        request(
            "POST",
            f"/api/runs/{run['run_id']}/decision",
            json={"decision": "approve", "operator": "test-operator"},
        )
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"
    assert decided.json()["approval"]["action_executed"] is False

    duplicate = asyncio.run(
        request(
            "POST",
            f"/api/runs/{run['run_id']}/decision",
            json={"decision": "reject", "operator": "test-operator"},
        )
    )
    assert duplicate.status_code == 409


def test_dashboard_reports_source_and_runtime_state():
    configure_status_mock()
    response = asyncio.run(request("GET", "/api/dashboard"))
    assert response.status_code == 200
    body = response.json()
    assert body["source_name"] == "Wikimedia Status"
    assert body["incident_count"] == len(WIKIMEDIA_STATUS_INCIDENTS)
    assert body["data_mode"] == "live"


def test_knowledge_upload_retrieval_chat_and_session_memory():
    reset_rate_limits()
    session_id = "knowledge-test-session"
    document = """# 支付服务值班手册

支付服务出现 5xx 峰值时，先检查数据库连接池耗尽指标和最近发布记录。
任何流量切换都必须经过人工审批，验证错误率恢复后再扩大流量。
"""
    uploaded = asyncio.run(
        request(
            "POST",
            "/api/knowledge/documents",
            files={"file": ("payment-runbook.md", document.encode("utf-8"), "text/markdown")},
        )
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["name"] == "payment-runbook.md"
    assert uploaded.json()["chunk_count"] >= 1

    status_response = asyncio.run(request("GET", "/api/knowledge/status"))
    assert status_response.status_code == 200
    assert status_response.json()["document_count"] >= 1
    status_body = status_response.json()
    assert status_body["retrieval_mode"] in {"混合检索准备中", "混合检索 RAG"}
    assert "BM25" in status_body["retriever"]
    assert "多语言" in status_body["retriever"]
    assert status_body["source_document_count"] >= 1
    assert "外部事故类比" in status_body["source_types"]

    answered = asyncio.run(
        request(
            "POST",
            "/api/chat",
            json={"question": "支付服务 5xx 峰值应该检查什么？", "session_id": session_id},
        )
    )
    assert answered.status_code == 200
    body = answered.json()
    assert body["analysis_mode"] == "retrieval-unconfigured"
    assert body["citations"][0]["document_name"] == "payment-runbook.md"
    assert body["citations"][0]["retrieval_signals"]
    assert body["memory_turns"] == 1

    history = asyncio.run(request("GET", f"/api/sessions/{session_id}"))
    assert history.status_code == 200
    assert [item["role"] for item in history.json()] == ["user", "assistant"]

    cleared = asyncio.run(request("DELETE", f"/api/sessions/{session_id}"))
    assert cleared.status_code == 200
    assert cleared.json()["cleared"] is True


def test_knowledge_upload_rejects_unsupported_files():
    reset_rate_limits()
    response = asyncio.run(
        request(
            "POST",
            "/api/knowledge/documents",
            files={"file": ("secret.exe", b"not a document", "application/octet-stream")},
        )
    )
    assert response.status_code == 422


def test_github_pages_origin_is_allowed_without_credentials():
    response = asyncio.run(
        request(
            "OPTIONS",
            "/api/chat",
            headers={
                "Origin": "https://antolizama931-debug.github.io",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://antolizama931-debug.github.io"
    assert response.headers.get("access-control-allow-credentials") != "true"


def test_approved_run_executes_complete_dry_run_and_creates_reviewable_knowledge():
    reset_rate_limits()
    created = asyncio.run(
        request(
            "POST",
            "/api/runs",
            json={
                "session_id": "closed-loop-test",
                "incident": {
                    "description": "数据库连接池耗尽导致订单接口持续超时，需要执行标准处置。",
                    "service": "orders-api",
                    "severity": "SEV-2",
                    "signals": [
                        {"kind": "metric", "name": "db.pool", "value": "100%"},
                        {"kind": "log", "name": "db.timeout", "value": "increased"},
                    ],
                },
            },
        )
    )
    assert created.status_code == 201
    run = created.json()
    assert run["runbook"]["runbook_id"] == "RB-DATABASE-PRESSURE"

    approved = asyncio.run(
        request(
            "POST",
            f"/api/runs/{run['run_id']}/decision",
            json={"decision": "approve", "operator": "test-operator"},
        )
    )
    assert approved.json()["status"] == "approved"

    executed = asyncio.run(
        request(
            "POST",
            f"/api/runs/{run['run_id']}/execute",
            json={
                "operator": "test-operator",
                "confirmation": "EXECUTE DRY RUN",
                "simulated_result": "success",
            },
        )
    )
    assert executed.status_code == 200
    body = executed.json()
    assert body["status"] == "recovered"
    assert body["execution"]["simulated"] is True
    assert body["execution"]["validation_passed"] is True
    assert body["approval"]["action_executed"] is False
    assert body["knowledge_candidate"]["status"] == "pending-review"
    assert [item["tool"] for item in body["tool_calls"][-3:]] == [
        "runbook.execute",
        "remediation.validate",
        "knowledge.draft",
    ]

    reviewed = asyncio.run(
        request(
            "POST",
            f"/api/runs/{run['run_id']}/knowledge-review",
            json={"decision": "accept", "reviewer": "test-reviewer"},
        )
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["knowledge_candidate"]["status"] == "accepted"


def test_enterprise_alert_webhook_is_authenticated_and_deduplicated():
    reset_rate_limits()
    original_token = main_module.WEBHOOK_TOKEN
    main_module.WEBHOOK_TOKEN = "test-webhook-token"
    payload = {
        "title": "订单接口数据库超时",
        "description": "订单接口持续返回超时，数据库连接池利用率达到百分之百。",
        "service": "orders-api",
        "severity": "SEV-2",
        "fingerprint": "orders-db-timeout-test",
        "source": "test-alertmanager",
        "signals": [{"kind": "metric", "name": "db.pool", "value": "100%"}],
    }
    try:
        unauthorized = asyncio.run(request("POST", "/api/integrations/alerts", json=payload))
        assert unauthorized.status_code == 401

        first = asyncio.run(
            request(
                "POST",
                "/api/integrations/alerts",
                json=payload,
                headers={"X-OnCall-Token": "test-webhook-token"},
            )
        )
        assert first.status_code == 202
        assert first.json()["duplicated"] is False
        assert first.json()["run_id"]

        second = asyncio.run(
            request(
                "POST",
                "/api/integrations/alerts",
                json=payload,
                headers={"X-OnCall-Token": "test-webhook-token"},
            )
        )
        assert second.status_code == 202
        assert second.json()["duplicated"] is True
        assert second.json()["occurrences"] == 2
        assert second.json()["run_id"] == first.json()["run_id"]
    finally:
        main_module.WEBHOOK_TOKEN = original_token
