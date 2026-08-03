"""Synthetic, non-sensitive incidents used by the public demo and tests."""

from __future__ import annotations

from .models import IncidentRequest, Scenario, Severity, Signal, SignalKind


SCENARIOS: dict[str, Scenario] = {
    "latency": Scenario(
        key="latency",
        title="Latency regression",
        subtitle="payment-api · SEV-1",
        request=IncidentRequest(
            description=(
                "Checkout p95 latency increased from 180 ms to 2.8 s shortly after a deployment. "
                "HTTP 503 errors and retry volume are increasing, while database utilization is stable."
            ),
            service="payment-api",
            severity=Severity.SEV1,
            change_event="deploy 8f3c1a completed 94 seconds before the latency increase",
            signals=[
                Signal(kind=SignalKind.METRIC, name="http.p95_latency", value="2.81 s, baseline 180 ms"),
                Signal(kind=SignalKind.METRIC, name="http.retry_rate", value="+312%"),
                Signal(kind=SignalKind.METRIC, name="db.cpu", value="44%, stable"),
                Signal(kind=SignalKind.LOG, name="upstream_errors", value="HTTP 503 from inventory-api"),
            ],
        ),
    ),
    "database": Scenario(
        key="database",
        title="Database saturation",
        subtitle="orders-db · SEV-2",
        request=IncidentRequest(
            description=(
                "Order writes are timing out. The database connection pool is full and a reporting "
                "query overlaps the first timeout event."
            ),
            service="orders-api",
            severity=Severity.SEV2,
            signals=[
                Signal(kind=SignalKind.METRIC, name="db.pool.utilization", value="100%"),
                Signal(kind=SignalKind.TRACE, name="query.q-731", value="71% of database execution time"),
                Signal(kind=SignalKind.LOG, name="orders-api", value="connection acquisition timeout"),
            ],
        ),
    ),
    "memory": Scenario(
        key="memory",
        title="Memory pressure",
        subtitle="search-worker · SEV-2",
        request=IncidentRequest(
            description=(
                "Search workers restart repeatedly. Resident memory grows with cache cardinality and "
                "containers terminate with OOMKilled."
            ),
            service="search-worker",
            severity=Severity.SEV2,
            change_event="cache-v2 feature flag enabled before memory growth started",
            signals=[
                Signal(kind=SignalKind.METRIC, name="container.rss", value="monotonic growth to 2 GiB limit"),
                Signal(kind=SignalKind.METRIC, name="cache.cardinality", value="+487%"),
                Signal(kind=SignalKind.LOG, name="kubernetes.reason", value="OOMKilled"),
            ],
        ),
    ),
}

