"""Bundled replay records copied from GitHub's official public status API.

The live endpoint remains the primary source. These small records keep the demo
usable when GitHub Status is unavailable and make automated tests reproducible.
Only the first public updates are retained so the demo does not leak a later root
cause into the evidence presented to the agent.
"""

from __future__ import annotations


GITHUB_STATUS_SNAPSHOT_AT = "2026-08-03T01:44:04.521Z"

GITHUB_STATUS_INCIDENTS: list[dict] = [
    {
        "id": "sj1tzyrx599x",
        "name": "Incident with Copilot AI Model Providers",
        "status": "resolved",
        "impact": "minor",
        "created_at": "2026-08-01T18:03:05.539Z",
        "incident_updates": [
            {
                "status": "investigating",
                "body": "We are investigating reports of degraded performance for Copilot AI Model Providers",
                "display_at": "2026-08-01T18:03:05.616Z",
                "affected_components": [
                    {
                        "name": "Copilot AI Model Providers",
                        "old_status": "operational",
                        "new_status": "degraded_performance",
                    }
                ],
            },
            {
                "status": "investigating",
                "body": "We are seeing increased error rates from specific upstream AI Model Providers",
                "display_at": "2026-08-01T18:03:15.483Z",
                "affected_components": [
                    {
                        "name": "Copilot AI Model Providers",
                        "old_status": "degraded_performance",
                        "new_status": "degraded_performance",
                    }
                ],
            },
        ],
        "components": [{"name": "Copilot AI Model Providers"}],
    },
    {
        "id": "q27ttsnp0x4g",
        "name": "Actions runs are experiencing failures to start",
        "status": "resolved",
        "impact": "major",
        "created_at": "2026-07-13T13:32:22.192Z",
        "incident_updates": [
            {
                "status": "investigating",
                "body": "We are investigating reports of degraded availability for Actions",
                "display_at": "2026-07-13T13:32:22.327Z",
                "affected_components": [
                    {
                        "name": "Actions",
                        "old_status": "operational",
                        "new_status": "partial_outage",
                    }
                ],
            },
            {
                "status": "investigating",
                "body": "Pages is experiencing degraded performance. We are continuing to investigate.",
                "display_at": "2026-07-13T13:32:44.537Z",
                "affected_components": [
                    {
                        "name": "Pages",
                        "old_status": "operational",
                        "new_status": "degraded_performance",
                    },
                    {
                        "name": "Actions",
                        "old_status": "partial_outage",
                        "new_status": "partial_outage",
                    },
                ],
            },
        ],
        "components": [{"name": "Actions"}, {"name": "Pages"}],
    },
    {
        "id": "dfpfsngcwywf",
        "name": "Disruption with some GitHub services",
        "status": "resolved",
        "impact": "minor",
        "created_at": "2026-07-14T08:21:17.628Z",
        "incident_updates": [
            {
                "status": "investigating",
                "body": "We are investigating reports of impacted performance for some GitHub services.",
                "display_at": "2026-07-14T08:21:17.715Z",
                "affected_components": [],
            },
            {
                "status": "investigating",
                "body": "Codespaces is experiencing degraded performance. We are continuing to investigate.",
                "display_at": "2026-07-14T08:22:37.117Z",
                "affected_components": [
                    {
                        "name": "Codespaces",
                        "old_status": "operational",
                        "new_status": "degraded_performance",
                    }
                ],
            },
        ],
        "components": [{"name": "Codespaces"}],
    },
]
