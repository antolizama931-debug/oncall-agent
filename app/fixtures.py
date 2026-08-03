"""Verified real-incident snapshots used by deterministic tests."""

from __future__ import annotations

from .statuspage import snapshot_scenarios


SCENARIOS = {scenario.key: scenario for scenario in snapshot_scenarios()}
