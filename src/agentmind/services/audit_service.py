from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_sqlite() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class AuditService:
    """Local audit event storage and query service."""

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
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    module TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT DEFAULT '',
                    user_id TEXT DEFAULT '',
                    trace_id TEXT DEFAULT '',
                    agent_id TEXT DEFAULT '',
                    risk_level TEXT DEFAULT 'low',
                    status TEXT DEFAULT 'success',
                    message TEXT DEFAULT '',
                    payload TEXT NOT NULL DEFAULT '{}'
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_created ON audit_events(created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_module ON audit_events(module, created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_agent ON audit_events(agent_id, created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_risk ON audit_events(risk_level, created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_trace ON audit_events(trace_id, created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_actor ON audit_events(actor, created_at DESC)")
            conn.commit()
        finally:
            conn.close()

    async def record_event(
        self,
        *,
        module: str,
        action: str,
        actor: str = "",
        user_id: str = "",
        trace_id: str = "",
        agent_id: str = "",
        risk_level: str = "low",
        status: str = "success",
        message: str = "",
        payload: dict[str, Any] | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._record_event_sync,
            module=module,
            action=action,
            actor=actor,
            user_id=user_id,
            trace_id=trace_id,
            agent_id=agent_id,
            risk_level=risk_level,
            status=status,
            message=message,
            payload=payload,
        )

    def _record_event_sync(
        self,
        *,
        module: str,
        action: str,
        actor: str = "",
        user_id: str = "",
        trace_id: str = "",
        agent_id: str = "",
        risk_level: str = "low",
        status: str = "success",
        message: str = "",
        payload: dict[str, Any] | None = None,
    ) -> str:
        event_id = uuid.uuid4().hex
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO audit_events
                   (event_id, created_at, module, action, actor, user_id, trace_id,
                    agent_id, risk_level, status, message, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id,
                    _now_sqlite(),
                    module,
                    action,
                    actor,
                    user_id,
                    trace_id,
                    agent_id,
                    risk_level,
                    status,
                    message,
                    json.dumps(payload or {}, ensure_ascii=False),
                ),
            )
            conn.commit()
            return event_id
        finally:
            conn.close()

    async def record_routing_decision(
        self,
        *,
        trace_id: str,
        agent_id: str,
        strategy: str,
        confidence: float,
        actor: str = "",
        user_id: str = "",
        risk_level: str = "low",
        payload: dict[str, Any] | None = None,
    ) -> str:
        event_payload = {
            "strategy": strategy,
            "confidence": confidence,
        }
        event_payload.update(payload or {})
        return await self.record_event(
            module="routing",
            action="decision",
            actor=actor,
            user_id=user_id,
            trace_id=trace_id,
            agent_id=agent_id,
            risk_level=risk_level,
            status="success",
            message=f"routing decision: {strategy} -> {agent_id}",
            payload=event_payload,
        )

    async def record_cpe_decision(
        self,
        *,
        request,
        decision,
        actor: str = "system",
        payload: dict[str, Any] | None = None,
    ) -> str:
        decision_status = getattr(decision.status, "value", str(decision.status))
        event_payload = {
            "component": "CPE",
            "decision_status": decision_status,
            "reason": decision.reason,
            "agent_security_level": request.agent_security_level,
            "memory_count": len(request.memory_items),
        }
        event_payload.update(decision.audit_payload or {})
        event_payload.update(payload or {})
        status = self._cpe_event_status(decision_status)
        return await self.record_event(
            module="governance",
            action="cpe_decision",
            actor=actor,
            user_id=request.user_id,
            trace_id=request.trace_id,
            agent_id=request.agent_id,
            risk_level=decision.risk_level,
            status=status,
            message=f"CPE decision: {decision_status}",
            payload=event_payload,
        )

    def _cpe_event_status(self, decision_status: str) -> str:
        if decision_status == "allow":
            return "success"
        if decision_status == "require_approval":
            return "approval_required"
        return "blocked"

    async def query_events(
        self,
        *,
        limit: int = 50,
        module: str = "",
        action: str = "",
        agent_id: str = "",
        risk_level: str = "",
        trace_id: str = "",
        actor: str = "",
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._query_events_sync,
            limit=limit,
            module=module,
            action=action,
            agent_id=agent_id,
            risk_level=risk_level,
            trace_id=trace_id,
            actor=actor,
        )

    def _query_events_sync(
        self,
        *,
        limit: int = 50,
        module: str = "",
        action: str = "",
        agent_id: str = "",
        risk_level: str = "",
        trace_id: str = "",
        actor: str = "",
    ) -> list[dict[str, Any]]:
        filters = []
        values: list[Any] = []
        for column, value in [
            ("module", module),
            ("action", action),
            ("agent_id", agent_id),
            ("risk_level", risk_level),
            ("trace_id", trace_id),
            ("actor", actor),
        ]:
            if value:
                filters.append(f"{column}=?")
                values.append(value)

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        values.append(limit)

        conn = self._get_conn()
        try:
            rows = conn.execute(
                f"SELECT * FROM audit_events {where_clause} ORDER BY created_at DESC, rowid DESC LIMIT ?",
                values,
            ).fetchall()
            return [self._format_event(dict(row)) for row in rows]
        finally:
            conn.close()

    def _format_event(self, row: dict[str, Any]) -> dict[str, Any]:
        row["payload"] = json.loads(row.get("payload") or "{}")
        return row
