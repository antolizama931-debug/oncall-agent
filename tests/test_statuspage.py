import asyncio

import httpx

from app.real_data import GITHUB_STATUS_INCIDENTS
from app.statuspage import GitHubStatusClient


def test_live_statuspage_data_is_sanitized_and_mapped():
    incident = {
        **GITHUB_STATUS_INCIDENTS[0],
        "name": "<b>Provider incident</b>",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.githubstatus.com"
        return httpx.Response(200, json={"incidents": [incident]})

    client = GitHubStatusClient(transport=httpx.MockTransport(handler), cache_seconds=0)
    scenarios = asyncio.run(client.get_scenarios())

    assert scenarios[0].title == "Provider incident"
    assert scenarios[0].data_mode == "live"
    assert scenarios[0].request.source_incident_id == "sj1tzyrx599x"
    assert scenarios[0].request.signals[0].source == "github_status_api"


def test_statuspage_failure_uses_verified_real_snapshot():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    client = GitHubStatusClient(transport=httpx.MockTransport(handler), cache_seconds=0)
    scenarios = asyncio.run(client.get_scenarios())

    assert client.last_mode == "verified-snapshot"
    assert scenarios[0].data_mode == "verified-snapshot"
    assert scenarios[0].source_url.startswith("https://www.githubstatus.com/incidents/")
