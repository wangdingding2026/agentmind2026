"""SessionService — persistent session and working-memory state."""

import asyncio
import sqlite3
import uuid
from datetime import datetime, timezone


def _now_sqlite() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class SessionService:
    """Persist active session, force-new flag, and recent working memory."""

    _working_memory_max = 20

    def __init__(self, store=None):
        if store is None:
            from agentmind.memory.sqlite_store import SqliteMemoryStore
            store = SqliteMemoryStore()
        self._store = store
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        return self._store._get_conn()

    def _ensure_schema(self):
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_state (
                    user_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    force_new_next INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS working_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    ts TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_working_memory_user_id ON working_memory(user_id, id)"
            )
            conn.commit()
        finally:
            conn.close()

    async def new_session(self, user_id: str) -> str:
        if not user_id:
            return ""
        return await asyncio.to_thread(self._new_session_sync, user_id)

    def _new_session_sync(self, user_id: str) -> str:
        conn = self._get_conn()
        try:
            self._close_active_conversation(conn, user_id)
            sid = f"sess-{uuid.uuid4().hex[:8]}"
            now = _now_sqlite()
            conn.execute(
                """INSERT INTO session_state(user_id, session_id, force_new_next, updated_at)
                   VALUES (?, ?, 1, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     session_id=excluded.session_id,
                     force_new_next=1,
                     updated_at=excluded.updated_at""",
                (user_id, sid, now),
            )
            conn.execute("DELETE FROM working_memory WHERE user_id=?", (user_id,))
            conn.commit()
            return sid
        finally:
            conn.close()

    def _close_active_conversation(self, conn, user_id: str):
        row = conn.execute(
            """SELECT conversation_id FROM conversations
               WHERE user_id=? AND status='active'
               ORDER BY last_message_at DESC LIMIT 1""",
            (user_id,),
        ).fetchone()
        if row:
            from agentmind.memory.components.conversation_merger import ConversationMerger
            ConversationMerger().close_conversation(conn, row["conversation_id"])

    def get_active_session(self, user_id: str) -> str | None:
        if not user_id:
            return None
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT session_id FROM session_state WHERE user_id=?",
                (user_id,),
            ).fetchone()
            return row["session_id"] if row else None
        finally:
            conn.close()

    def get_active_conversation_id(self, user_id: str) -> str | None:
        if not user_id:
            return None
        conn = self._get_conn()
        try:
            row = conn.execute(
                """SELECT conversation_id FROM conversations
                   WHERE user_id=? AND status='active'
                   ORDER BY last_message_at DESC LIMIT 1""",
                (user_id,),
            ).fetchone()
            return row["conversation_id"] if row else None
        finally:
            conn.close()

    def ensure_active_session(self, user_id: str) -> tuple[str, bool]:
        if not user_id:
            return "", False
        current = self.get_active_session(user_id)
        if current:
            return current, False
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO session_state
                   (user_id, session_id, force_new_next, updated_at)
                   VALUES (?, ?, 0, ?)""",
                (user_id, sid, _now_sqlite()),
            )
            conn.commit()
            return sid, True
        finally:
            conn.close()

    def consume_force_new(self, user_id: str) -> bool:
        if not user_id:
            return False
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT force_new_next FROM session_state WHERE user_id=?",
                (user_id,),
            ).fetchone()
            value = bool(row and row["force_new_next"])
            if value:
                conn.execute(
                    "UPDATE session_state SET force_new_next=0, updated_at=? WHERE user_id=?",
                    (_now_sqlite(), user_id),
                )
                conn.commit()
            return value
        finally:
            conn.close()

    def add_to_working_memory(self, user_id: str, role: str, content: str):
        if not user_id or not content:
            return
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO working_memory(user_id, role, content, ts) VALUES (?, ?, ?, ?)",
                (user_id, role, (content or "")[:500], _now_sqlite()),
            )
            rows = conn.execute(
                """SELECT id FROM working_memory
                   WHERE user_id=? ORDER BY id DESC LIMIT -1 OFFSET ?""",
                (user_id, self._working_memory_max),
            ).fetchall()
            if rows:
                old_ids = [r["id"] for r in rows]
                placeholders = ",".join("?" for _ in old_ids)
                conn.execute(f"DELETE FROM working_memory WHERE id IN ({placeholders})", old_ids)
            conn.commit()
        finally:
            conn.close()

    def clear_working_memory(self, user_id: str):
        if not user_id:
            return
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM working_memory WHERE user_id=?", (user_id,))
            conn.commit()
        finally:
            conn.close()

    def get_working_memory(self, user_id: str, limit: int = 3) -> list[dict]:
        if not user_id:
            return []
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT role, content, ts FROM working_memory
                   WHERE user_id=? ORDER BY id ASC""",
                (user_id,),
            ).fetchall()
        finally:
            conn.close()

        entries = [dict(r) for r in rows]
        rounds = []
        i = 0
        while i < len(entries):
            entry = entries[i]
            if entry["role"] == "user":
                nxt = entries[i + 1] if i + 1 < len(entries) else None
                assistant = nxt["content"] if nxt and nxt["role"] == "assistant" else ""
                rounds.append({"user": entry["content"], "assistant": assistant, "ts": entry["ts"]})
                i += 2 if nxt and nxt["role"] == "assistant" else 1
            else:
                i += 1
        return rounds[-limit:] if len(rounds) > limit else rounds
