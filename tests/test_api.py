import asyncio

import httpx

from app.main import app


async def request(method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def test_health_endpoint():
    response = asyncio.run(request("GET", "/api/health"))
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["deepseek_configured"] is False


def test_scenario_can_be_analyzed_end_to_end():
    scenario_response = asyncio.run(request("GET", "/api/scenarios/latency"))
    assert scenario_response.status_code == 200

    response = asyncio.run(
        request("POST", "/api/analyze", json=scenario_response.json()["request"])
    )
    assert response.status_code == 200
    body = response.json()
    assert body["analysis_mode"] == "deterministic-unconfigured"
    assert body["hypotheses"][0]["confidence"] >= 0.80
    assert body["recommendation"]["approval_required"] is True


def test_invalid_short_description_is_rejected():
    response = asyncio.run(request("POST", "/api/analyze", json={"description": "short"}))
    assert response.status_code == 422
