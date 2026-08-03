"""只读获取 Wikimedia 官方 Statuspage 事故并提供可验证快照降级。"""

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
from .real_data import WIKIMEDIA_STATUS_INCIDENTS, WIKIMEDIA_STATUS_SNAPSHOT_AT


DEFAULT_CACHE_SECONDS = 300
DEFAULT_SCENARIO_LIMIT = 20
DEFAULT_PER_SOURCE_LIMIT = 20


@dataclass(frozen=True)
class StatusSource:
    """固定白名单中的官方状态页；调用方不能注入 URL。"""

    key: str
    name: str
    api_url: str
    site_url: str


WIKIMEDIA_SOURCE = StatusSource(
    key="wikimedia",
    name="Wikimedia Status",
    api_url="https://www.wikimediastatus.net/api/v2/incidents.json",
    site_url="https://www.wikimediastatus.net",
)
STATUS_SOURCES = (WIKIMEDIA_SOURCE,)

# Backward-compatible constants used by existing integrations.
GITHUB_SOURCE = WIKIMEDIA_SOURCE
GITHUB_STATUS_API = WIKIMEDIA_SOURCE.api_url
GITHUB_STATUS_SITE = WIKIMEDIA_SOURCE.site_url


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


STATUS_LABELS_ZH = {
    "investigating": "调查中",
    "identified": "已定位",
    "monitoring": "监控恢复中",
    "resolved": "已解决",
    "postmortem": "复盘中",
    "scheduled": "计划维护",
    "in_progress": "处理中",
    "verifying": "验证中",
    "completed": "已完成",
}
IMPACT_LABELS_ZH = {
    "critical": "严重影响",
    "major": "重大影响",
    "minor": "较低影响",
    "none": "无明显影响",
    "unknown": "影响待确认",
}


def _translate_terms(value: str) -> str:
    """翻译通用运维短语，产品名、模型名、区域代码保持不变。"""
    replacements = (
        ("Wikipedia and other wikis", "Wikipedia 及其他 Wiki"),
        ("Wikis", "Wiki 站点"),
        ("wikis", "Wiki 站点"),
        ("Connectivity issues from Russia", "俄罗斯地区连接异常"),
        ("Ongoing network outage, users might be unable to reach the wikis", "网络中断，部分用户无法访问 Wiki 站点"),
        ("reporting errors with edits", "编辑操作出现错误"),
        ("were in read only mode", "进入只读模式"),
        ("Edits to", "对"),
        ("are delayed", "的编辑出现延迟"),
        ("Issues and degraded performance accessing", "访问异常且性能下降："),
        ("Reading", "页面读取"),
        ("Editing", "内容编辑"),
        ("Copilot AI Model Providers", "Copilot AI 模型服务提供商"),
        ("AI Model Providers", "AI 模型服务提供商"),
        ("Network Performance", "网络性能"),
        ("HTTP 5XX Errors", "HTTP 5XX 错误"),
        ("socket connection", "套接字连接"),
        ("failed meeting joins", "会议加入失败"),
        ("availability", "可用性"),
        ("elevated errors", "错误率升高"),
        ("Metrics Queries", "Metrics 查询"),
        ("services", "服务"),
        ("Istanbul", "伊斯坦布尔"),
    )
    result = value
    for source, target in replacements:
        result = re.sub(re.escape(source), target, result, flags=re.IGNORECASE)
    return result.strip()


def _localized_title(title: str, service: str, source_name: str) -> str:
    """把常见 Statuspage 事故标题转换为中文优先标题。"""
    patterns: tuple[tuple[str, Any], ...] = (
        (r"^Incident with (.+)$", lambda match: f"{_translate_terms(match.group(1))}异常"),
        (r"^Degraded availability(?: for)? (.+)$", lambda match: f"{_translate_terms(match.group(1))}可用性下降"),
        (r"^Network Performance Issues in (.+)$", lambda match: f"{_translate_terms(match.group(1))}地区网络性能异常"),
        (r"^Increased (.+) in (.+)$", lambda match: f"{_translate_terms(match.group(2))}地区{_translate_terms(match.group(1))}增加"),
        (r"^(.+) experiencing elevated errors$", lambda match: f"{_translate_terms(match.group(1))}错误率升高"),
        (r"^(.+) socket connection slowness and failed meeting joins$", lambda match: f"{_translate_terms(match.group(1))}套接字连接缓慢，会议加入失败"),
        (r"^Delayed (.+)$", lambda match: f"{_translate_terms(match.group(1))}数据延迟"),
    )
    for pattern, formatter in patterns:
        if match := re.match(pattern, title, flags=re.IGNORECASE):
            return formatter(match)
    translated = _translate_terms(title)
    if re.search(r"[\u3400-\u9fff]", translated):
        return translated
    translated_service = _translate_terms(service)
    if re.search(r"[\u3400-\u9fff]", translated_service):
        return f"{translated_service}服务异常"
    return f"{source_name}公开服务异常"


def _localized_update(status: str, service: str) -> str:
    status_key = status.lower()
    service_name = _translate_terms(service)
    prefix = STATUS_LABELS_ZH.get(status_key, "状态更新")
    detail = {
        "investigating": "官方正在调查异常原因。",
        "identified": "官方已定位问题，正在实施修复。",
        "monitoring": "修复措施已实施，正在观察服务恢复情况。",
        "resolved": "事故已解决，服务状态已恢复。",
        "postmortem": "事故已结束，官方正在整理复盘信息。",
    }.get(status_key, "官方已发布新的事故进展。")
    return f"{prefix}：{service_name}。{detail}"


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
    source: StatusSource = WIKIMEDIA_SOURCE,
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
    display_title = _localized_title(title, service, source.name)

    signals: list[Signal] = [
        Signal(
            kind=SignalKind.ALERT,
            name=f"status_update_{index}",
            value=f"{_plain_text(update.get('status'), 40)}: {text}",
            timestamp=_parse_timestamp(update.get("display_at") or update.get("created_at")),
            source=signal_source,
            display_name=f"第 {index} 次官方更新",
            display_value=_localized_update(_plain_text(update.get("status"), 40), service),
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
            display_name="公开影响等级",
            display_value=IMPACT_LABELS_ZH.get(impact, "影响待确认"),
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
        display_title=display_title,
        display_summary=(
            f"{_translate_terms(service)}发生公开服务异常。"
            f"当前状态：{STATUS_LABELS_ZH.get(_plain_text(incident.get('status'), 40).lower(), '待确认')}；"
            f"影响等级：{IMPACT_LABELS_ZH.get(impact, '影响待确认')}；"
            f"官方已发布 {len(raw_updates)} 条更新。"
        ),
    )


def snapshot_scenarios() -> list[Scenario]:
    fetched_at = datetime.fromisoformat(WIKIMEDIA_STATUS_SNAPSHOT_AT.replace("Z", "+00:00"))
    return [
        incident_to_scenario(
            item,
            data_mode="verified-snapshot",
            fetched_at=fetched_at,
            source=WIKIMEDIA_SOURCE,
        )
        for item in WIKIMEDIA_STATUS_INCIDENTS
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
        headers = {
            "Accept": "application/json",
            "User-Agent": (
                "OnCallAgent/0.6 "
                "(https://github.com/antolizama931-debug/oncall-agent; "
                "antolizama931-debug@users.noreply.github.com)"
            ),
        }
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

        # Wikimedia 快照只在实时源失败时补位，且明确标记为快照。
        if WIKIMEDIA_SOURCE in self.sources and WIKIMEDIA_SOURCE.key not in succeeded:
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
    """兼容旧调用方名称；实际读取 Wikimedia Status。"""

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
            sources=(WIKIMEDIA_SOURCE,),
            transport=transport,
        )
