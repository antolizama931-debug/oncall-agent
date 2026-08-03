import asyncio
import os

import httpx

# Tests must never inherit a developer's real model credential from .env. An
# explicitly present empty value prevents load_dotenv() from loading the key.
os.environ["DEEPSEEK_API_KEY"] = ""

from app.main import app, daily_usage, request_windows, status_client
from app.real_data import GITHUB_STATUS_INCIDENTS


async def request(method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def configure_status_mock() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"incidents": GITHUB_STATUS_INCIDENTS})

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
    assert body["evidence"][0]["source"].startswith("github_status:")
    assert body["hypotheses"][0]["confidence"] >= 0.50
    assert body["recommendation"]["approval_required"] is True


def test_scenarios_expose_verifiable_provenance():
    configure_status_mock()
    response = asyncio.run(request("GET", "/api/scenarios"))
    assert response.status_code == 200
    scenario = response.json()[0]
    assert scenario["source_name"] == "GitHub Status"
    assert scenario["source_url"].startswith("https://www.githubstatus.com/incidents/")
    assert scenario["data_mode"] in {"live", "verified-snapshot"}


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
            json={"scenario_key": scenarios[0]["key"], "session_id": session_id},
        )
    )
    assert created.status_code == 201
    run = created.json()
    assert run["status"] == "awaiting-approval"
    assert [item["tool"] for item in run["tool_calls"]] == [
        "github_status.read",
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
    assert body["source_name"] == "GitHub Status"
    assert body["incident_count"] == len(GITHUB_STATUS_INCIDENTS)
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
    assert status_response.json()["retriever"] == "BM25 lexical"

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
