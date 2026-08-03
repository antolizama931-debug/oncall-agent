import asyncio

import httpx

from app.connectors import EnterpriseToolGateway
from app.models import IncidentRequest, Severity


def test_enterprise_gateway_collects_real_returned_observations_without_inventing_data():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/metrics/query":
            return httpx.Response(
                200,
                json={
                    "signals": [
                        {
                            "kind": "metric",
                            "name": "http.error_rate",
                            "value": "12.4%",
                            "display_name": "接口错误率",
                            "display_value": "最近五分钟为 12.4%",
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"signals": [], "artifacts": []})

    gateway = EnterpriseToolGateway(
        base_url="https://tool-gateway.internal",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )
    incident = IncidentRequest(
        description="订单接口错误率持续升高，需要自动收集企业遥测证据。",
        service="orders-api",
        severity=Severity.SEV2,
    )
    enriched, calls = asyncio.run(gateway.collect(incident))

    assert len(calls) == 4
    assert all(call.read_only is True for call in calls)
    assert enriched.signals[0].name == "http.error_rate"
    assert enriched.signals[0].value == "12.4%"


def test_enterprise_gateway_failure_is_audited_and_does_not_block_other_evidence():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "unavailable"})

    gateway = EnterpriseToolGateway(
        base_url="https://tool-gateway.internal",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )
    incident = IncidentRequest(
        description="服务发生异常，但企业遥测网关当前不可用。",
        service="orders-api",
    )
    enriched, calls = asyncio.run(gateway.collect(incident))

    assert enriched == incident
    assert len(calls) == 4
    assert all(call.status == "failed" for call in calls)
    assert all("明确降级" in call.output_summary for call in calls)
