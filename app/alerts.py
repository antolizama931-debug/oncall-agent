"""Authenticated enterprise alert inbox with deterministic deduplication."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from .models import AlertEventRequest, AlertReceipt


class AlertInboxStore:
    """Persist normalized alerts and collapse repeated notifications by fingerprint."""

    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self.database_path = data_dir / "runtime.db"
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_inbox (
                fingerprint TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                occurrences INTEGER NOT NULL,
                run_id TEXT,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                received_at TEXT NOT NULL
            )
            """
        )
        self._connection.commit()
        self._lock = Lock()

    @staticmethod
    def fingerprint(event: AlertEventRequest) -> str:
        if event.fingerprint:
            return event.fingerprint.strip()
        labels = "|".join(f"{key}={event.labels[key]}" for key in sorted(event.labels))
        material = f"{event.source}|{event.environment}|{event.service}|{event.title}|{labels}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]

    def ingest(self, event: AlertEventRequest) -> AlertReceipt:
        fingerprint = self.fingerprint(event)
        now = datetime.now(timezone.utc)
        with self._lock:
            row = self._connection.execute(
                "SELECT event_id, occurrences, run_id FROM alert_inbox WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            duplicated = row is not None
            event_id = row[0] if row else f"ALERT-{secrets.token_hex(4).upper()}"
            occurrences = int(row[1]) + 1 if row else 1
            run_id = row[2] if row else None
            self._connection.execute(
                """
                INSERT INTO alert_inbox(
                    fingerprint, event_id, occurrences, run_id, status, payload, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    occurrences = excluded.occurrences,
                    status = excluded.status,
                    payload = excluded.payload,
                    received_at = excluded.received_at
                """,
                (
                    fingerprint,
                    event_id,
                    occurrences,
                    run_id,
                    event.status,
                    event.model_dump_json(),
                    now.isoformat(),
                ),
            )
            self._connection.commit()
        return AlertReceipt(
            event_id=event_id,
            fingerprint=fingerprint,
            duplicated=duplicated,
            occurrences=occurrences,
            run_id=run_id,
            status=event.status,
            received_at=now,
        )

    def link_run(self, fingerprint: str, run_id: str) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE alert_inbox SET run_id = ? WHERE fingerprint = ?", (run_id, fingerprint)
            )
            self._connection.commit()

    def list(self, limit: int = 100) -> list[AlertReceipt]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT event_id, fingerprint, occurrences, run_id, status, received_at
                FROM alert_inbox ORDER BY received_at DESC LIMIT ?
                """,
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [
            AlertReceipt(
                event_id=row[0],
                fingerprint=row[1],
                duplicated=row[2] > 1,
                occurrences=row[2],
                run_id=row[3],
                status=row[4],
                received_at=datetime.fromisoformat(row[5]),
            )
            for row in rows
        ]
