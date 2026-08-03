"""Read-only adapter for GitHub's public Atlassian Statuspage feed."""

from __future__ import annotations

import html
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from .models import IncidentRequest, Scenario, Severity, Signal, SignalKind
from .real_data import GITHUB_STATUS_INCIDENTS, GITHUB_STATUS_SNAPSHOT_AT


# Fixed URL: callers cannot supply a host, which prevents SSRF through this adapter.
GITHUB_STATUS_API = "https://www.githubstatus.com/api/v2/incidents.json"
GITHUB_STATUS_SITE = "https://www.githubstatus.com"
DEFAULT_CACHE_SECONDS = 300
DEFAULT_SCENARIO_LIMIT = 6


class StatusPageError(RuntimeError):
    """Raised when the upstream public incident feed cannot be validated."""


def _plain_text(value: Any, max_length: int = 2000) -> str:
    """Remove Statuspage HTML and normalize whitespace before using external text."""
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
    replay_update_limit: int = 3,
) -> Scenario:
    """Convert one public incident into an early-timeline diagnostic replay."""
    incident_id = _plain_text(incident.get("id"), 120)
    title = _plain_text(incident.get("name"), 240)
    if not incident_id or not title:
        raise StatusPageError("Incident record is missing an id or name")

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
        update_pairs = [({}, f"GitHub Status reported: {title}.")]
    update_texts = [text for _, text in update_pairs]

    components = _component_names(incident)
    service = ", ".join(components)[:120] or "GitHub services"
    impact = _plain_text(incident.get("impact"), 30).lower() or "unknown"
    source_url = f"{GITHUB_STATUS_SITE}/incidents/{incident_id}"

    signals: list[Signal] = [
        Signal(
            kind=SignalKind.ALERT,
            name=f"status_update_{index}",
            value=f"{_plain_text(update.get('status'), 40)}: {text}",
            timestamp=_parse_timestamp(update.get("display_at") or update.get("created_at")),
            source="github_status_api",
        )
        for index, (update, text) in enumerate(update_pairs, start=1)
    ]
    signals.append(
        Signal(
            kind=SignalKind.ALERT,
            name="reported_impact",
            value=impact,
            timestamp=_parse_timestamp(incident.get("created_at")),
            source="github_status_api",
        )
    )

    severity = _severity(impact)
    description = f"{title}. {update_texts[0]}"
    return Scenario(
        key=f"github-{incident_id}",
        title=title,
        subtitle=f"{service} · {severity.value}",
        request=IncidentRequest(
            description=description,
            service=service,
            severity=severity,
            signals=signals,
            source_name="GitHub Status",
            source_url=source_url,
            source_incident_id=incident_id,
        ),
        source_name="GitHub Status",
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
        incident_to_scenario(item, data_mode="verified-snapshot", fetched_at=fetched_at)
        for item in GITHUB_STATUS_INCIDENTS
    ]


class GitHubStatusClient:
    """Fetch, validate, map, and briefly cache public incident records."""

    def __init__(
        self,
        *,
        cache_seconds: int = DEFAULT_CACHE_SECONDS,
        scenario_limit: int = DEFAULT_SCENARIO_LIMIT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.cache_seconds = max(cache_seconds, 0)
        self.scenario_limit = max(1, min(scenario_limit, 20))
        self.transport = transport
        self._cached_at = 0.0
        self._cached: list[Scenario] | None = None
        self.last_mode = "not-loaded"
        self.last_error: str | None = None

    async def get_scenarios(self) -> list[Scenario]:
        now = time.monotonic()
        if self._cached is not None and now - self._cached_at < self.cache_seconds:
            return self._cached

        try:
            timeout = httpx.Timeout(8.0, connect=4.0)
            headers = {"Accept": "application/json", "User-Agent": "oncall-agent-demo/0.2"}
            async with httpx.AsyncClient(
                timeout=timeout,
                headers=headers,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = await client.get(GITHUB_STATUS_API)
                response.raise_for_status()
                payload = response.json()
            incidents = payload.get("incidents") if isinstance(payload, dict) else None
            if not isinstance(incidents, list) or not incidents:
                raise StatusPageError("GitHub Status returned no incident records")
            fetched_at = datetime.now(timezone.utc)
            scenarios = [
                incident_to_scenario(item, data_mode="live", fetched_at=fetched_at)
                for item in incidents[: self.scenario_limit]
                if isinstance(item, dict)
            ]
            if not scenarios:
                raise StatusPageError("GitHub Status records could not be mapped")
            self.last_mode = "live"
            self.last_error = None
        except (httpx.HTTPError, ValueError, StatusPageError) as exc:
            scenarios = snapshot_scenarios()
            self.last_mode = "verified-snapshot"
            self.last_error = str(exc)[:240]

        self._cached = scenarios
        self._cached_at = now
        return scenarios
