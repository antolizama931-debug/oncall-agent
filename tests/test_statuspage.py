import asyncio

import httpx

from app.real_data import WIKIMEDIA_STATUS_INCIDENTS
from app.statuspage import GitHubStatusClient, MultiStatusClient


def test_live_statuspage_data_is_sanitized_and_mapped():
    incident = {
        **WIKIMEDIA_STATUS_INCIDENTS[0],
        "name": "<b>Provider incident</b>",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.wikimediastatus.net"
        return httpx.Response(200, json={"incidents": [incident]})

    client = GitHubStatusClient(transport=httpx.MockTransport(handler), cache_seconds=0)
    scenarios = asyncio.run(client.get_scenarios())

    assert scenarios[0].title == "Provider incident"
    assert scenarios[0].data_mode == "live"
    assert scenarios[0].request.source_incident_id == "wfdnbnv00w3r"
    assert scenarios[0].request.signals[0].source == "wikimedia_status_api"
    assert scenarios[0].display_title != scenarios[0].title
    assert "异常" in scenarios[0].display_title
    assert scenarios[0].request.signals[0].display_name == "第 1 次官方更新"
    assert "监控恢复中" in scenarios[0].request.signals[0].display_value


def test_statuspage_failure_uses_verified_real_snapshot():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    client = GitHubStatusClient(transport=httpx.MockTransport(handler), cache_seconds=0)
    scenarios = asyncio.run(client.get_scenarios())

    assert client.last_mode == "verified-snapshot"
    assert scenarios[0].data_mode == "verified-snapshot"
    assert scenarios[0].source_url.startswith("https://www.wikimediastatus.net/incidents/")


def test_status_client_reads_only_wikimedia_primary_domain():
    def handler(request: httpx.Request) -> httpx.Response:
        incident = {**WIKIMEDIA_STATUS_INCIDENTS[0], "id": f"{request.url.host}-incident"}
        return httpx.Response(200, json={"incidents": [incident]})

    client = MultiStatusClient(transport=httpx.MockTransport(handler), cache_seconds=0)
    scenarios = asyncio.run(client.get_scenarios())

    assert client.last_mode == "live"
    assert {item.source_name for item in scenarios} == {"Wikimedia Status"}
    assert all(item.source_url.startswith("https://") for item in scenarios)
    assert all(item.display_title and item.display_summary for item in scenarios)
    assert any("异常" in item.display_title for item in scenarios)
