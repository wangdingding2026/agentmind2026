"""TraceService — persistent routing trace storage outside user memory."""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone


def _now_sqlite() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class TraceService:
    """Store routing traces in trace.db."""

    def __init__(self, db_path: str = ""):
        if db_path:
            self._db_path = db_path
        else:
            from agentmind.storage.db import DATA_DIR
            self._db_path = str(DATA_DIR / "trace.db")
        self._ensure_schema()

    def _get_conn(self):
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _ensure_schema(self):
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS routing_traces (
                    trace_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    user_id TEXT DEFAULT '',
                    agent_id TEXT DEFAULT '',
                    strategy TEXT DEFAULT '',
                    confidence REAL DEFAULT 0.0,
                    fallback_chain TEXT DEFAULT '[]',
                    reply_text TEXT DEFAULT '',
                    raw_message TEXT DEFAULT '',
                    candidates TEXT DEFAULT '[]',
                    security_flagged INTEGER DEFAULT 0,
                    payload TEXT NOT NULL DEFAULT '{}'
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_routing_traces_created ON routing_traces(created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_routing_traces_user ON routing_traces(user_id, created_at DESC)")
            conn.commit()
        finally:
            conn.close()

    async def record_decision(self, trace_id: str, decision, user_id: str = ""):
        await asyncio.to_thread(self._record_decision_sync, trace_id, decision, user_id)

    def _record_decision_sync(self, trace_id: str, decision, user_id: str = ""):
        context = decision.context
        payload = {
            "agent_id": decision.agent_id,
            "strategy": decision.strategy,
            "confidence": decision.confidence,
            "fallback_chain": decision.fallback_chain,
            "reply_text": decision.reply_text[:200] if decision.reply_text else "",
            "raw_message": context.raw_message[:500] if context else "",
            "candidates": context.candidates if context else [],
            "security_flagged": context.security_flagged if context else False,
        }
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO routing_traces
                   (trace_id, created_at, user_id, agent_id, strategy, confidence,
                    fallback_chain, reply_text, raw_message, candidates, security_flagged, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trace_id,
                    _now_sqlite(),
                    user_id,
                    payload["agent_id"],
                    payload["strategy"],
                    float(payload["confidence"] or 0.0),
                    json.dumps(payload["fallback_chain"], ensure_ascii=False),
                    payload["reply_text"],
                    payload["raw_message"],
                    json.dumps(payload["candidates"], ensure_ascii=False),
                    1 if payload["security_flagged"] else 0,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    async def record_strategy_run(self, trace_id: str, strategy: str, payload: dict | None = None):
        payload = payload or {}
        await asyncio.to_thread(self._record_strategy_run_sync, trace_id, strategy, payload)

    def _record_strategy_run_sync(self, trace_id: str, strategy: str, payload: dict):
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO routing_traces
                   (trace_id, created_at, strategy, payload)
                   VALUES (?, ?, ?, ?)""",
                (trace_id, _now_sqlite(), strategy, json.dumps(payload, ensure_ascii=False)),
            )
            conn.commit()
        finally:
            conn.close()

    async def get_trace(self, trace_id: str) -> dict | None:
        return await asyncio.to_thread(self._get_trace_sync, trace_id)

    def _get_trace_sync(self, trace_id: str) -> dict | None:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM routing_traces WHERE trace_id=?",
                (trace_id,),
            ).fetchone()
            if not row:
                return None
            return self._format_trace(dict(row))
        finally:
            conn.close()

    def _format_trace(self, row: dict) -> dict:
        payload = json.loads(row.get("payload") or "{}")
        summary = f"[{row.get('strategy', '')}] -> {row.get('agent_id', '')} (conf={row.get('confidence', 0.0)})"
        row["content"] = json.dumps(payload, ensure_ascii=False)
        row["summary"] = summary
        row["memory_id"] = f"trace-{row['trace_id']}"
        row["source_agent"] = "agentmind"
        row["source_task_id"] = row["trace_id"]
        row["tags"] = ["routing_trace"] + ([f"user:{row['user_id']}"] if row.get("user_id") else [])
        row["access_level"] = "private"
        return row

    async def query_traces(self, limit: int = 20, user_id: str = "") -> list[dict]:
        return await asyncio.to_thread(self._query_traces_sync, limit, user_id)

    def _query_traces_sync(self, limit: int = 20, user_id: str = "") -> list[dict]:
        conn = self._get_conn()
        try:
            if user_id:
                rows = conn.execute(
                    "SELECT * FROM routing_traces WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM routing_traces ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._format_trace(dict(r)) for r in rows]
        finally:
            conn.close()
