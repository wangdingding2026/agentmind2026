from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TASK_EVENT_TYPES = {
    "task_started",
    "routing_started",
    "agent_selected",
    "execution_started",
    "partial_output",
    "completed",
    "failed",
}


def _now_sqlite() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class TaskEventService:
    """Local task timeline event storage.

    This service owns the storage contract only. Runtime producers, replay, and
    panel views are intentionally left to later observability packages.
    """

    def __init__(self, db_path: str = ""):
        if db_path:
            self._db_path = db_path
        else:
            from agentmind.storage.db import DATA_DIR

            self._db_path = str(DATA_DIR / "trace.db")
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _get_conn(self):
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _ensure_schema(self) -> None:
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_events (
                    event_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    seq INTEGER NOT NULL DEFAULT 10,
                    agent_id TEXT DEFAULT '',
                    message TEXT DEFAULT '',
                    payload TEXT NOT NULL DEFAULT '{}'
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_events_trace ON task_events(trace_id, seq, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_events_type ON task_events(event_type, created_at DESC)")
            conn.commit()
        finally:
            conn.close()

    async def record_event(
        self,
        *,
        trace_id: str,
        event_type: str,
        seq: int = 10,
        agent_id: str = "",
        message: str = "",
        payload: dict[str, Any] | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._record_event_sync,
            trace_id=trace_id,
            event_type=event_type,
            seq=seq,
            agent_id=agent_id,
            message=message,
            payload=payload,
        )

    def _record_event_sync(
        self,
        *,
        trace_id: str,
        event_type: str,
        seq: int = 10,
        agent_id: str = "",
        message: str = "",
        payload: dict[str, Any] | None = None,
    ) -> str:
        self._validate_event_type(event_type)
        event_id = uuid.uuid4().hex
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO task_events
                   (event_id, created_at, trace_id, event_type, seq, agent_id, message, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id,
                    _now_sqlite(),
                    trace_id,
                    event_type,
                    seq,
                    agent_id,
                    message,
                    json.dumps(payload or {}, ensure_ascii=False),
                ),
            )
            conn.commit()
            return event_id
        finally:
            conn.close()

    async def query_events(self, *, trace_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._query_events_sync,
            trace_id=trace_id,
            limit=limit,
        )

    def _query_events_sync(self, *, trace_id: str, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT * FROM task_events
                   WHERE trace_id=?
                   ORDER BY seq ASC, created_at ASC, rowid ASC
                   LIMIT ?""",
                (trace_id, limit),
            ).fetchall()
            return [self._format_event(dict(row)) for row in rows]
        finally:
            conn.close()

    def _format_event(self, row: dict[str, Any]) -> dict[str, Any]:
        row["payload"] = json.loads(row.get("payload") or "{}")
        return row

    def _validate_event_type(self, event_type: str) -> None:
        if event_type not in TASK_EVENT_TYPES:
            raise ValueError(f"unsupported task event type: {event_type}")
