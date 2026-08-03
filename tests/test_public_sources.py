import asyncio

import httpx

from app.knowledge import KnowledgeBaseStore
from app.public_sources import PublicKnowledgeRecord, WikimediaKnowledgeClient


def test_wikimedia_client_filters_drafts_and_keeps_namespaces():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("generator") == "categorymembers":
            pages = {
                "1": {
                    "pageid": 1,
                    "title": "Incidents/2026-05-13 wdqs",
                    "fullurl": "https://wikitech.wikimedia.org/wiki/Incidents/2026-05-13_wdqs",
                    "extract": "document status: final\nWDQS requests failed after backend saturation.",
                },
                "2": {
                    "pageid": 2,
                    "title": "Incidents/2026-04-30 draft",
                    "fullurl": "https://wikitech.wikimedia.org/wiki/Incidents/2026-04-30_draft",
                    "extract": "document status: draft\nUnreviewed notes.",
                },
            }
        else:
            pages = {
                "3": {
                    "pageid": 3,
                    "title": "Incident response/Runbook",
                    "fullurl": "https://wikitech.wikimedia.org/wiki/Incident_response/Runbook",
                    "extract": "Acknowledge the alert, appoint an incident coordinator, and record actions.",
                }
            }
        return httpx.Response(200, json={"query": {"pages": pages}})

    client = WikimediaKnowledgeClient(
        cache_seconds=0,
        incident_limit=10,
        transport=httpx.MockTransport(handler),
    )
    documents = asyncio.run(client.get_documents())

    assert client.last_mode == "live"
    assert any(item.namespace == "wikimedia_incidents" for item in documents)
    assert any(item.namespace == "wikimedia_runbooks" for item in documents)
    assert any(item.namespace == "external_postmortems" for item in documents)
    assert not any("draft" in item.title.lower() for item in documents)


def test_authoritative_wikimedia_evidence_outranks_external_analogy():
    store = KnowledgeBaseStore(max_documents=2)
    records = [
        PublicKnowledgeRecord(
            key="external",
            title="外部案例",
            content="数据库连接池耗尽导致请求超时，应检查连接数。",
            source_type="外部事故类比",
            namespace="external_postmortems",
            source_url="https://example.com/external",
            authority_level=0.30,
            applicable_for_action=False,
            organization="External",
        ),
        PublicKnowledgeRecord(
            key="wikimedia",
            title="Wikimedia 数据库 Runbook",
            content="数据库连接池耗尽导致请求超时，应检查连接数。",
            source_type="Wikimedia Runbook",
            namespace="wikimedia_runbooks",
            source_url="https://wikitech.wikimedia.org/wiki/MariaDB/troubleshooting",
            authority_level=1.0,
            applicable_for_action=True,
            organization="Wikimedia",
        ),
        PublicKnowledgeRecord(
            key="wikimedia-status",
            title="Wikimedia 状态更新",
            content="数据库连接池耗尽导致请求超时，应检查连接数。",
            source_type="Wikimedia Status 真实事故",
            namespace="wikimedia_status",
            source_url="https://www.wikimediastatus.net/incidents/example",
            authority_level=1.0,
            applicable_for_action=False,
            organization="Wikimedia",
        ),
    ]
    store.sync_public_documents(records)

    results = store.search("数据库连接池耗尽怎么处理？", top_k=2)

    assert results[0].organization == "Wikimedia"
    assert results[0].namespace == "wikimedia_runbooks"
    assert results[0].applicable_for_action is True
    assert results[1].namespace == "wikimedia_status"
