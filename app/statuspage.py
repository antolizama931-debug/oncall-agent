"""只读聚合多个官方 Atlassian Statuspage 事故源。"""

from __future__ import annotations

import asyncio
import html
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from .models import IncidentRequest, Scenario, Severity, Signal, SignalKind
from .real_data import GITHUB_STATUS_INCIDENTS, GITHUB_STATUS_SNAPSHOT_AT


DEFAULT_CACHE_SECONDS = 300
DEFAULT_SCENARIO_LIMIT = 36
DEFAULT_PER_SOURCE_LIMIT = 12


@dataclass(frozen=True)
class StatusSource:
    """固定白名单中的官方状态页；调用方不能注入 URL。"""

    key: str
    name: str
    api_url: str
    site_url: str


GITHUB_SOURCE = StatusSource(
    key="github",
    name="GitHub Status",
    api_url="https://www.githubstatus.com/api/v2/incidents.json",
    site_url="https://www.githubstatus.com",
)
CLOUDFLARE_SOURCE = StatusSource(
    key="cloudflare",
    name="Cloudflare Status",
    api_url="https://www.cloudflarestatus.com/api/v2/incidents.json",
    site_url="https://www.cloudflarestatus.com",
)
DATADOG_SOURCE = StatusSource(
    key="datadog",
    name="Datadog Status",
    api_url="https://status.datadoghq.com/api/v2/incidents.json",
    site_url="https://status.datadoghq.com",
)
STATUS_SOURCES = (GITHUB_SOURCE, CLOUDFLARE_SOURCE, DATADOG_SOURCE)

# Backward-compatible constants used by existing integrations.
GITHUB_STATUS_API = GITHUB_SOURCE.api_url
GITHUB_STATUS_SITE = GITHUB_SOURCE.site_url


class StatusPageError(RuntimeError):
    """上游公开事故源无法通过结构校验。"""


def _plain_text(value: Any, max_length: int = 2000) -> str:
    """移除 Statuspage HTML，并在进入模型前规范化外部文本。"""
    text = html.unescape(str(value or ""))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_length]


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _severity(impact: str) -> Severity:
    return {
        "critical": Severity.SEV1,
        "major": Severity.SEV1,
        "minor": Severity.SEV2,
        "none": Severity.SEV3,
    }.get(impact.lower(), Severity.UNKNOWN)


def _component_names(incident: dict[str, Any]) -> list[str]:
    names = {
        _plain_text(component.get("name"), 80)
        for component in incident.get("components") or []
        if isinstance(component, dict)
    }
    for update in incident.get("incident_updates") or []:
        if not isinstance(update, dict):
            continue
        for component in update.get("affected_components") or []:
            if isinstance(component, dict):
                names.add(_plain_text(component.get("name"), 80))
    return sorted(name for name in names if name)


def incident_to_scenario(
    incident: dict[str, Any],
    *,
    data_mode: str,
    fetched_at: datetime,
    source: StatusSource = GITHUB_SOURCE,
    replay_update_limit: int = 3,
) -> Scenario:
    """把一条公开事故转换为保留来源的早期时间线回放。"""
    incident_id = _plain_text(incident.get("id"), 120)
    title = _plain_text(incident.get("name"), 240)
    if not incident_id or not title:
        raise StatusPageError("事故记录缺少 id 或 name")

    raw_updates = [
        item for item in (incident.get("incident_updates") or []) if isinstance(item, dict)
    ]
    raw_updates.sort(key=lambda item: str(item.get("display_at") or item.get("created_at") or ""))
    update_pairs = [
        (item, text)
        for item in raw_updates[:replay_update_limit]
        if (text := _plain_text(item.get("body")))
    ]
    if not update_pairs:
        update_pairs = [({}, f"{source.name} reported: {title}.")]
    update_texts = [text for _, text in update_pairs]

    components = _component_names(incident)
    service = ", ".join(components)[:120] or f"{source.name} services"
    impact = _plain_text(incident.get("impact"), 30).lower() or "unknown"
    source_url = f"{source.site_url}/incidents/{incident_id}"
    signal_source = f"{source.key}_status_api"

    signals: list[Signal] = [
        Signal(
            kind=SignalKind.ALERT,
            name=f"status_update_{index}",
            value=f"{_plain_text(update.get('status'), 40)}: {text}",
            timestamp=_parse_timestamp(update.get("display_at") or update.get("created_at")),
            source=signal_source,
        )
        for index, (update, text) in enumerate(update_pairs, start=1)
    ]
    signals.append(
        Signal(
            kind=SignalKind.ALERT,
            name="reported_impact",
            value=impact,
            timestamp=_parse_timestamp(incident.get("created_at")),
            source=signal_source,
        )
    )

    severity = _severity(impact)
    return Scenario(
        key=f"{source.key}-{incident_id}",
        title=title,
        subtitle=f"{source.name}｜{service}｜{severity.value}",
        request=IncidentRequest(
            description=f"{title}. {update_texts[0]}",
            service=service,
            severity=severity,
            signals=signals,
            source_name=source.name,
            source_url=source_url,
            source_incident_id=incident_id,
        ),
        source_name=source.name,
        source_url=source_url,
        source_incident_id=incident_id,
        data_mode=data_mode,
        fetched_at=fetched_at,
        incident_status=_plain_text(incident.get("status"), 40) or "unknown",
        impact=impact,
        started_at=_parse_timestamp(incident.get("started_at") or incident.get("created_at")),
        update_count=len(raw_updates),
        components=components,
    )


def snapshot_scenarios() -> list[Scenario]:
    fetched_at = datetime.fromisoformat(GITHUB_STATUS_SNAPSHOT_AT.replace("Z", "+00:00"))
    return [
        incident_to_scenario(
            item,
            data_mode="verified-snapshot",
            fetched_at=fetched_at,
            source=GITHUB_SOURCE,
        )
        for item in GITHUB_STATUS_INCIDENTS
    ]


class MultiStatusClient:
    """并行读取、校验、合并并短时缓存多个固定官方事故源。"""

    def __init__(
        self,
        *,
        cache_seconds: int = DEFAULT_CACHE_SECONDS,
        scenario_limit: int = DEFAULT_SCENARIO_LIMIT,
        per_source_limit: int = DEFAULT_PER_SOURCE_LIMIT,
        sources: tuple[StatusSource, ...] = STATUS_SOURCES,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.cache_seconds = max(cache_seconds, 0)
        self.scenario_limit = max(1, min(scenario_limit, 60))
        self.per_source_limit = max(1, min(per_source_limit, 20))
        self.sources = sources
        self.source_names = [item.name for item in sources]
        self.transport = transport
        self._cached_at = 0.0
        self._cached: list[Scenario] | None = None
        self.last_mode = "not-loaded"
        self.last_error: str | None = None

    async def _fetch_source(
        self,
        client: httpx.AsyncClient,
        source: StatusSource,
    ) -> list[Scenario]:
        response = await client.get(source.api_url)
        response.raise_for_status()
        payload = response.json()
        incidents = payload.get("incidents") if isinstance(payload, dict) else None
        if not isinstance(incidents, list) or not incidents:
            raise StatusPageError(f"{source.name} 没有返回事故记录")
        fetched_at = datetime.now(timezone.utc)
        scenarios: list[Scenario] = []
        for item in incidents[: self.per_source_limit]:
            if not isinstance(item, dict):
                continue
            try:
                scenarios.append(
                    incident_to_scenario(
                        item,
                        data_mode="live",
                        fetched_at=fetched_at,
                        source=source,
                    )
                )
            except StatusPageError:
                continue
        if not scenarios:
            raise StatusPageError(f"{source.name} 的记录无法映射")
        return scenarios

    async def get_scenarios(self) -> list[Scenario]:
        now = time.monotonic()
        if self._cached is not None and now - self._cached_at < self.cache_seconds:
            return self._cached

        timeout = httpx.Timeout(10.0, connect=4.0)
        headers = {"Accept": "application/json", "User-Agent": "oncall-agent-demo/0.4"}
        errors: list[str] = []
        scenarios: list[Scenario] = []
        succeeded: set[str] = set()
        async with httpx.AsyncClient(
            timeout=timeout,
            headers=headers,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            results = await asyncio.gather(
                *(self._fetch_source(client, source) for source in self.sources),
                return_exceptions=True,
            )

        for source, result in zip(self.sources, results, strict=True):
            if isinstance(result, Exception):
                errors.append(f"{source.name}: {str(result)[:160]}")
                continue
            scenarios.extend(result)
            succeeded.add(source.key)

        # GitHub 快照只在 GitHub 实时源失败时补位，且明确标记为快照。
        if GITHUB_SOURCE in self.sources and GITHUB_SOURCE.key not in succeeded:
            scenarios.extend(snapshot_scenarios())

        if not succeeded:
            scenarios = snapshot_scenarios()
            self.last_mode = "verified-snapshot"
        elif errors:
            self.last_mode = "partial-live"
        else:
            self.last_mode = "live"
        self.last_error = "；".join(errors)[:500] or None
        scenarios.sort(
            key=lambda item: item.started_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        self._cached = scenarios[: self.scenario_limit]
        self._cached_at = now
        return self._cached


class GitHubStatusClient(MultiStatusClient):
    """兼容旧调用方的单一 GitHub Status 客户端。"""

    def __init__(
        self,
        *,
        cache_seconds: int = DEFAULT_CACHE_SECONDS,
        scenario_limit: int = 6,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            cache_seconds=cache_seconds,
            scenario_limit=scenario_limit,
            per_source_limit=scenario_limit,
            sources=(GITHUB_SOURCE,),
            transport=transport,
        )
