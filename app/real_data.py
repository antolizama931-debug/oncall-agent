"""可验证的 Wikimedia Status 离线回放快照。

在线接口始终是首选数据源。快照仅在网络不可用时保证演示和测试可运行；
只保存事故的早期公开更新，避免把事后根因提前泄漏给 Agent。
"""

from __future__ import annotations


WIKIMEDIA_STATUS_SNAPSHOT_AT = "2026-08-03T08:00:00Z"

WIKIMEDIA_STATUS_INCIDENTS: list[dict] = [
    {
        "id": "wfdnbnv00w3r",
        "name": "Connectivity issues from Russia",
        "status": "resolved",
        "impact": "minor",
        "created_at": "2026-07-30T10:08:30.000Z",
        "incident_updates": [
            {
                "status": "monitoring",
                "body": "There are reports of connectivity issues from Russia outside of our control. The issues mostly affect image and media serving.",
                "display_at": "2026-07-30T10:08:30.000Z",
                "affected_components": [{"name": "Reading"}],
            },
            {
                "status": "resolved",
                "body": "This incident has been resolved.",
                "display_at": "2026-07-31T10:09:39.709Z",
                "affected_components": [{"name": "Reading"}],
            },
        ],
        "components": [{"name": "Reading"}],
    },
    {
        "id": "7m1vqs2gwnmq",
        "name": "Ongoing network outage, users might be unable to reach the wikis",
        "status": "resolved",
        "impact": "major",
        "created_at": "2026-07-01T14:44:01.505Z",
        "incident_updates": [
            {
                "status": "investigating",
                "body": "We are currently investigating this issue.",
                "display_at": "2026-07-01T14:44:01.542Z",
                "affected_components": [],
            },
            {
                "status": "investigating",
                "body": "The outage is currently recovering at 14:45 UTC.",
                "display_at": "2026-07-01T14:45:22.046Z",
                "affected_components": [],
            },
        ],
        "components": [],
    },
    {
        "id": "kq46rrxd2yy4",
        "name": "Wikipedia and other wikis reporting errors with edits",
        "status": "resolved",
        "impact": "none",
        "created_at": "2026-04-02T11:17:43.176Z",
        "incident_updates": [
            {
                "status": "investigating",
                "body": "We are investigating an issue causing a number of edits to wikis to fail.",
                "display_at": "2026-04-02T11:17:43.237Z",
                "affected_components": [{"name": "Editing"}],
            },
            {
                "status": "resolved",
                "body": "This incident has been resolved.",
                "display_at": "2026-04-02T14:27:14.869Z",
                "affected_components": [{"name": "Editing"}],
            },
        ],
        "components": [{"name": "Editing"}],
    },
    {
        "id": "z7qjmqtrh8yq",
        "name": "Wikis were in read only mode",
        "status": "resolved",
        "impact": "minor",
        "created_at": "2026-03-05T15:36:54.413Z",
        "incident_updates": [
            {
                "status": "investigating",
                "body": "We are aware of issues with accessing some wikis, and we are investigating.",
                "display_at": "2026-03-05T15:36:54.511Z",
                "affected_components": [{"name": "Reading"}, {"name": "Editing"}],
            },
            {
                "status": "identified",
                "body": "The issue has been identified and a fix is being implemented.",
                "display_at": "2026-03-05T16:11:51.073Z",
                "affected_components": [{"name": "Reading"}, {"name": "Editing"}],
            },
        ],
        "components": [{"name": "Reading"}, {"name": "Editing"}],
    },
    {
        "id": "ncw3k9b4ynz6",
        "name": "Edits to Wikipedia and other wikis are delayed",
        "status": "resolved",
        "impact": "minor",
        "created_at": "2026-03-03T10:09:45.326Z",
        "incident_updates": [
            {
                "status": "identified",
                "body": "We discovered an issue with our database servers and are working on a fix.",
                "display_at": "2026-03-03T10:09:45.412Z",
                "affected_components": [{"name": "Editing"}],
            },
            {
                "status": "monitoring",
                "body": "We think we fixed the database issue and are monitoring the result.",
                "display_at": "2026-03-03T10:17:50.025Z",
                "affected_components": [{"name": "Editing"}],
            },
        ],
        "components": [{"name": "Editing"}],
    },
    {
        "id": "qdkw27z7d2yt",
        "name": "Issues and degraded performance accessing Wikis",
        "status": "resolved",
        "impact": "major",
        "created_at": "2026-02-26T16:25:38.306Z",
        "incident_updates": [
            {
                "status": "monitoring",
                "body": "A fix has been implemented and we are monitoring the results.",
                "display_at": "2026-02-26T16:25:38.411Z",
                "affected_components": [{"name": "Reading"}, {"name": "Editing"}],
            },
            {
                "status": "resolved",
                "body": "This incident has been resolved.",
                "display_at": "2026-02-26T16:58:38.188Z",
                "affected_components": [{"name": "Reading"}, {"name": "Editing"}],
            },
        ],
        "components": [{"name": "Reading"}, {"name": "Editing"}],
    },
]

# 兼容旧测试或第三方导入；新代码只使用 Wikimedia 常量。
GITHUB_STATUS_SNAPSHOT_AT = WIKIMEDIA_STATUS_SNAPSHOT_AT
GITHUB_STATUS_INCIDENTS = WIKIMEDIA_STATUS_INCIDENTS
