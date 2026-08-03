"""Read-only enterprise telemetry gateway connector.

The original SuperBizAgent project demonstrates MCP-based tool discovery, but its
bundled log and metric servers generate mock observations. This adapter preserves
the useful tool-gateway boundary while requiring a separately deployed, trusted
enterprise gateway for real metrics, logs, traces, and change events.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx

from .models import Artifact, IncidentRequest, Signal, SignalKind, ToolCall


TOOL_ENDPOINTS: tuple[tuple[str, str, str], ...] = (
    ("telemetry.metrics.query", "/v1/metrics/query", "查询服务指标窗口"),
    ("telemetry.logs.search", "/v1/logs/search", "检索错误与异常日志"),
    ("telemetry.traces.search", "/v1/traces/search", "查询异常链路追踪"),
    ("telemetry.changes.read", "/v1/changes/recent", "读取最近发布与配置变更"),
)


class EnterpriseToolGateway:
    """Call fixed read-only endpoints configured only through server environment."""

    def __init__(
        self,
        *,
        base_url: str = "",
        token: str = "",
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = max(1.0, min(timeout_seconds, 30.0))
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    async def collect(self, incident: IncidentRequest) -> tuple[IncidentRequest, list[ToolCall]]:
        """Collect bounded observations; failures remain visible in the audit trace."""

        if not self.configured:
            return incident, []
        payload = {
            "service": incident.service,
            "environment": incident.environment,
            "window_minutes": 30,
            "incident_description": incident.description[:1000],
        }
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            results = await asyncio.gather(
                *(self._call(client, tool, path, purpose, payload) for tool, path, purpose in TOOL_ENDPOINTS)
            )

        signals = list(incident.signals)
        artifacts = list(incident.artifacts)
        tool_calls: list[ToolCall] = []
        for tool_call, response in results:
            tool_calls.append(tool_call)
            if response is None:
                continue
            signals.extend(self._signals(response.get("signals", []), tool_call.tool))
            artifacts.extend(self._artifacts(response.get("artifacts", []), tool_call.tool))

        # Retain the API model's safety limits even if a gateway misbehaves.
        enriched = incident.model_copy(
            update={"signals": signals[:40], "artifacts": artifacts[:5]}, deep=True
        )
        return enriched, tool_calls

    async def _call(
        self,
        client: httpx.AsyncClient,
        tool: str,
        path: str,
        purpose: str,
        payload: dict[str, Any],
    ) -> tuple[ToolCall, dict[str, Any] | None]:
        started = asyncio.get_running_loop().time()
        try:
            response = await client.post(path, json=payload)
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("工具网关响应必须是 JSON 对象")
            signal_count = len(body.get("signals", []))
            artifact_count = len(body.get("artifacts", []))
            status = "succeeded"
            summary = f"返回 {signal_count} 条结构化信号和 {artifact_count} 个证据片段"
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            body = None
            status = "failed"
            summary = f"只读工具调用失败：{type(exc).__name__}；调查继续并明确降级"
        duration_ms = int((asyncio.get_running_loop().time() - started) * 1000)
        return (
            ToolCall(
                sequence=1,
                tool=tool,
                purpose=purpose,
                status=status,
                output_summary=summary,
                read_only=True,
                duration_ms=max(0, duration_ms),
            ),
            body,
        )

    @staticmethod
    def _signals(items: Any, source: str) -> list[Signal]:
        if not isinstance(items, list):
            return []
        output: list[Signal] = []
        for item in items[:20]:
            if not isinstance(item, dict):
                continue
            try:
                kind = SignalKind(str(item.get("kind", "alert")))
                timestamp = item.get("timestamp")
                output.append(
                    Signal(
                        kind=kind,
                        name=str(item.get("name", "observation"))[:200],
                        value=str(item.get("value", "unknown"))[:4000],
                        timestamp=datetime.fromisoformat(timestamp) if timestamp else None,
                        source=source,
                        display_name=str(item.get("display_name", "企业遥测证据"))[:160],
                        display_value=str(item.get("display_value", item.get("value", "")))[:2000],
                    )
                )
            except (ValueError, TypeError):
                continue
        return output

    @staticmethod
    def _artifacts(items: Any, source: str) -> list[Artifact]:
        if not isinstance(items, list):
            return []
        output: list[Artifact] = []
        for index, item in enumerate(items[:3], start=1):
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            try:
                output.append(
                    Artifact(
                        name=str(item.get("name", f"{source}-{index}.txt"))[:160],
                        content=content[:20_000],
                        media_type=str(item.get("media_type", "text/plain"))[:100],
                    )
                )
            except ValueError:
                continue
        return output
