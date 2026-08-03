"""Wikimedia 主知识域与受隔离的外部类比资料。

数据治理规则：

* Wikimedia 事故与 Runbook 是可用于行动建议的权威主域；
* 外部企业事故仅作为低权重类比，不能直接生成生产操作；
* 所有远程地址固定在代码白名单中，用户输入不能改变抓取目标。
"""

from __future__ import annotations

import asyncio
import html
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx


WIKITECH_API = "https://wikitech.wikimedia.org/w/api.php"
WIKIMEDIA_INCIDENT_CATEGORY = "Category:Incident documentation"
WIKIMEDIA_RUNBOOK_TITLES = (
    "Incident response/Runbook",
    "Runbook",
    "Application servers/Runbook",
    "MariaDB/troubleshooting",
    "SLO/Runbook",
    "Performance/Guides/RUM Alert",
)


@dataclass(frozen=True)
class PublicKnowledgeRecord:
    key: str
    title: str
    content: str
    source_type: str
    namespace: str
    source_url: str
    authority_level: float
    applicable_for_action: bool
    organization: str
    media_type: str = "text/html"


EXTERNAL_ANALOGIES: tuple[PublicKnowledgeRecord, ...] = (
    PublicKnowledgeRecord(
        key="external-cloudflare-2026-02-20",
        title="Cloudflare 2026-02-20 BYOIP 路由事故",
        content=(
            "外部类比案例，不是 Wikimedia 操作手册。Cloudflare 公开复盘说明，"
            "BYOIP 地址管理流程的一次变更导致部分客户路由被撤回。该案例可用于理解"
            "BGP、路由策略和变更验证不足造成的网络故障，但不得直接生成 Wikimedia 操作命令。"
        ),
        source_type="外部事故类比",
        namespace="external_postmortems",
        source_url="https://blog.cloudflare.com/cloudflare-outage-february-20-2026/",
        authority_level=0.30,
        applicable_for_action=False,
        organization="Cloudflare",
    ),
    PublicKnowledgeRecord(
        key="external-google-cloud-network",
        title="Google Cloud 跨区域网络容量事故",
        content=(
            "外部类比案例，不是 Wikimedia 操作手册。Google Cloud 事故报告记录了"
            "BGP 路由撤回、网络容量下降和跨服务影响，可用于形成网络故障假设。"
            "任何处置都必须回到 Wikimedia Runbook 验证。"
        ),
        source_type="外部事故类比",
        namespace="external_postmortems",
        source_url="https://status.cloud.google.com/incidents/Nm7HSYZu9RqCY2HXRQQf",
        authority_level=0.30,
        applicable_for_action=False,
        organization="Google Cloud",
    ),
    PublicKnowledgeRecord(
        key="external-gitlab-loadbalancer-2026-04-11",
        title="GitLab 负载均衡器 5xx 超过 SLO 事故",
        content=(
            "外部类比案例，不是 Wikimedia 操作手册。GitLab 公开事故记录描述了"
            "高成本 compare 请求使部分 Gitaly 节点饱和，进一步阻塞 Puma 并产生 5xx。"
            "该案例只用于识别流量突增与下游饱和的故障模式。"
        ),
        source_type="外部事故类比",
        namespace="external_postmortems",
        source_url="https://gitlab.com/gitlab-com/gl-infra/production/-/work_items/21765",
        authority_level=0.30,
        applicable_for_action=False,
        organization="GitLab",
    ),
)

UPSTREAM_OFFICIAL_REFERENCES: tuple[PublicKnowledgeRecord, ...] = (
    PublicKnowledgeRecord(
        key="upstream-kubernetes-debug",
        title="Kubernetes 应用故障排查",
        content=(
            "Kubernetes 官方故障排查入口，覆盖 Pod、Service、StatefulSet、Init Container、"
            "容器终止信息和运行中容器调试。使用任何命令前必须确认 Wikimedia 当前集群版本、"
            "命名空间和变更权限。"
        ),
        source_type="上游组件官方文档",
        namespace="upstream_official_docs",
        source_url="https://kubernetes.io/docs/tasks/debug/debug-application/",
        authority_level=0.70,
        applicable_for_action=False,
        organization="Kubernetes",
    ),
    PublicKnowledgeRecord(
        key="upstream-prometheus-alerting",
        title="Prometheus 告警规则",
        content=(
            "Prometheus 官方告警规则说明，包含 pending、firing、for、keep_firing_for、labels、"
            "annotations 与 Alertmanager 通知关系。它用于解释告警语义，不替代 Wikimedia 的具体 Runbook。"
        ),
        source_type="上游组件官方文档",
        namespace="upstream_official_docs",
        source_url="https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/",
        authority_level=0.70,
        applicable_for_action=False,
        organization="Prometheus",
    ),
    PublicKnowledgeRecord(
        key="upstream-mariadb-monitoring",
        title="MariaDB 监控与日志",
        content=(
            "MariaDB 官方监控与日志入口，覆盖错误日志、慢查询日志、二进制日志和通用查询日志。"
            "只用于补充组件诊断；生产处置仍需匹配 Wikimedia MariaDB Runbook 和实际版本。"
        ),
        source_type="上游组件官方文档",
        namespace="upstream_official_docs",
        source_url="https://mariadb.com/kb/en/server-monitoring-logs/",
        authority_level=0.70,
        applicable_for_action=False,
        organization="MariaDB",
    ),
)


def _clean(value: Any, limit: int = 16_000) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:limit]


def _page_raw_content(page: dict[str, Any]) -> str:
    revisions = page.get("revisions") or []
    try:
        return str(revisions[0]["slots"]["main"]["content"])
    except (IndexError, KeyError, TypeError):
        return str(page.get("extract", ""))


def _page_content(page: dict[str, Any]) -> str:
    """读取 MediaWiki revision 主槽位并做轻量标记清理。"""
    text = _clean(_page_raw_content(page))
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"\{\{[^{}]{0,800}\}\}", " ", text, flags=re.S)
    text = re.sub(r"\[\[([^]|]+)\|([^]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^]]+)\]\]", r"\1", text)
    text = re.sub(r"={2,}\s*(.*?)\s*={2,}", r"\n\1\n", text)
    return _clean(text)


class WikimediaKnowledgeClient:
    """通过 MediaWiki Action API 获取最近事故复盘和固定 Runbook。"""

    def __init__(
        self,
        *,
        cache_seconds: int = 3600,
        incident_limit: int = 18,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.cache_seconds = max(cache_seconds, 0)
        self.incident_limit = max(4, min(incident_limit, 30))
        self.transport = transport
        self._cached_at = 0.0
        self._cached: list[PublicKnowledgeRecord] | None = None
        self._lock = asyncio.Lock()
        self.last_error: str | None = None
        self.last_mode = "not-loaded"

    async def _request(self, client: httpx.AsyncClient, params: dict[str, str]) -> list[dict[str, Any]]:
        response = await client.get(WIKITECH_API, params=params)
        response.raise_for_status()
        payload = response.json()
        pages = payload.get("query", {}).get("pages", {}) if isinstance(payload, dict) else {}
        if isinstance(pages, list):
            return [page for page in pages if isinstance(page, dict)]
        if isinstance(pages, dict):
            return [page for page in pages.values() if isinstance(page, dict)]
        return []

    async def _fetch_incidents(self, client: httpx.AsyncClient) -> list[PublicKnowledgeRecord]:
        pages = await self._request(
            client,
            {
                "action": "query",
                "generator": "categorymembers",
                "gcmtitle": WIKIMEDIA_INCIDENT_CATEGORY,
                "gcmtype": "page",
                "gcmlimit": "40",
                "gcmdir": "descending",
                "prop": "revisions|info",
                "rvprop": "content",
                "rvslots": "main",
                "inprop": "url",
                "format": "json",
                "formatversion": "2",
                "origin": "*",
            },
        )
        records: list[PublicKnowledgeRecord] = []
        for page in pages:
            title = _clean(page.get("title"), 300)
            raw_content = _page_raw_content(page)
            content = _page_content(page)
            if not title.startswith("Incidents/") or not content:
                continue
            status_match = re.search(
                r"(?:document status\s*:\s*|irdoc\s*\|\s*status\s*=\s*)([a-z-]+)",
                raw_content,
                re.I,
            )
            document_status = status_match.group(1).lower() if status_match else "unknown"
            if document_status == "review":
                document_status = "in-review"
            if document_status in {"draft", "unknown"}:
                continue
            page_id = str(page.get("pageid") or title)
            records.append(
                PublicKnowledgeRecord(
                    key=f"wikimedia-incident-{page_id}",
                    title=title.removeprefix("Incidents/"),
                    content=f"文档状态：{document_status}\n{content}",
                    source_type="Wikimedia 事故复盘",
                    namespace="wikimedia_incidents",
                    source_url=_clean(page.get("fullurl"), 800),
                    authority_level=1.0 if document_status == "final" else 0.85,
                    applicable_for_action=False,
                    organization="Wikimedia",
                )
            )
            if len(records) >= self.incident_limit:
                break
        return records

    async def _fetch_runbooks(self, client: httpx.AsyncClient) -> list[PublicKnowledgeRecord]:
        pages = await self._request(
            client,
            {
                "action": "query",
                "titles": "|".join(WIKIMEDIA_RUNBOOK_TITLES),
                "redirects": "1",
                "prop": "revisions|info",
                "rvprop": "content",
                "rvslots": "main",
                "inprop": "url",
                "format": "json",
                "formatversion": "2",
                "origin": "*",
            },
        )
        return [
            PublicKnowledgeRecord(
                key=f"wikimedia-runbook-{page.get('pageid', index)}",
                title=_clean(page.get("title"), 300),
                content=_page_content(page),
                source_type="Wikimedia Runbook",
                namespace="wikimedia_runbooks",
                source_url=_clean(page.get("fullurl"), 800),
                authority_level=1.0,
                applicable_for_action=True,
                organization="Wikimedia",
            )
            for index, page in enumerate(pages, start=1)
            if _page_content(page)
        ]

    async def get_documents(self) -> list[PublicKnowledgeRecord]:
        now = time.monotonic()
        if self._cached is not None and now - self._cached_at < self.cache_seconds:
            return list(self._cached)
        async with self._lock:
            now = time.monotonic()
            if self._cached is not None and now - self._cached_at < self.cache_seconds:
                return list(self._cached)
            timeout = httpx.Timeout(18.0, connect=5.0)
            headers = {
                "Accept": "application/json",
                "User-Agent": (
                    "OnCallAgent/0.6 "
                    "(https://github.com/antolizama931-debug/oncall-agent; "
                    "antolizama931-debug@users.noreply.github.com)"
                ),
            }
            try:
                async with httpx.AsyncClient(
                    timeout=timeout,
                    headers=headers,
                    follow_redirects=False,
                    transport=self.transport,
                ) as client:
                    incidents, runbooks = await asyncio.gather(
                        self._fetch_incidents(client), self._fetch_runbooks(client)
                    )
                self._cached = [
                    *runbooks,
                    *incidents,
                    *UPSTREAM_OFFICIAL_REFERENCES,
                    *EXTERNAL_ANALOGIES,
                ]
                self.last_mode = "live"
                self.last_error = None
            except Exception as exc:
                # 外部类比保留为低权重离线资料；失败不会阻塞事故控制台。
                self._cached = [*UPSTREAM_OFFICIAL_REFERENCES, *EXTERNAL_ANALOGIES]
                self.last_mode = "external-fallback"
                self.last_error = str(exc)[:400]
            self._cached_at = time.monotonic()
            return list(self._cached)
