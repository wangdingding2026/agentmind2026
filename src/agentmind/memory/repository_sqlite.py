"""SQLite repository boundary for canonical memory tables."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from agentmind.memory.dto import MemoryWriteCommand
from agentmind.memory.schema import initialize_memory_storage


def _now_sqlite() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _expires_sqlite(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


class SqliteMemoryRepository:
    def __init__(self, db_path: str = ""):
        if db_path:
            self._db_path = db_path
        else:
            from agentmind.storage import db as storage_db

            self._db_path = str(storage_db.DATA_DIR / "memory.db")
        initialize_memory_storage(self._db_path)

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    async def write_raw_and_card(self, command: MemoryWriteCommand) -> dict:
        return await asyncio.to_thread(self._write_raw_and_card_sync, command)

    def _write_raw_and_card_sync(self, command: MemoryWriteCommand) -> dict:
        memory_id = f"mem-{uuid.uuid4().hex[:16]}"
        raw_memory_id = memory_id
        now = command.created_at or _now_sqlite()
        tags_json = json.dumps(command.tags, ensure_ascii=False)
        metadata = json.dumps({"source_kind": command.source_kind}, ensure_ascii=False)
        card_text = f"{command.summary}\n\n{command.content}" if command.summary else command.content
        source_refs = json.dumps({
            "raw_memory_id": raw_memory_id,
            "source_agent": command.source_agent,
            "source_task_id": command.source_task_id,
        }, ensure_ascii=False)
        score_metadata = json.dumps({"memory_type": command.memory_type}, ensure_ascii=False)

        conn = self._get_conn()
        try:
            conn.execute("BEGIN")
            conn.execute(
                """INSERT INTO raw_memory
                   (memory_id, user_id, content, source_agent, source_task_id,
                    memory_type, conversation_id, created_at, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    raw_memory_id,
                    command.user_id,
                    command.content,
                    command.source_agent,
                    command.source_task_id,
                    command.memory_type,
                    command.conversation_id,
                    now,
                    metadata,
                ),
            )
            conn.execute(
                """INSERT INTO memory_cards
                   (memory_id, raw_memory_id, user_id, summary, source_agent, source_task_id,
                    memory_type, conversation_id, importance, tags, access_level,
                    card_text, source_refs, score_metadata, session_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    memory_id,
                    raw_memory_id,
                    command.user_id,
                    command.summary,
                    command.source_agent,
                    command.source_task_id,
                    command.memory_type,
                    command.conversation_id,
                    0.5,
                    tags_json,
                    command.access_level,
                    card_text,
                    source_refs,
                    score_metadata,
                    command.session_id,
                    now,
                    now,
                ),
            )
            conn.commit()
            return self._get_card_sync(memory_id, conn=conn) or {
                "memory_id": memory_id,
                "raw_memory_id": raw_memory_id,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def search_cards(
        self,
        *,
        query: str,
        user_id: str = "",
        tags: list[str] | None = None,
        source_agent: str = "",
        access_levels: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict]:
        return await asyncio.to_thread(
            self._search_cards_sync,
            query,
            user_id,
            tags or [],
            source_agent,
            access_levels or [],
            limit,
        )

    def _search_cards_sync(
        self,
        query: str,
        user_id: str,
        tags: list[str],
        source_agent: str,
        access_levels: list[str],
        limit: int,
    ) -> list[dict]:
        clauses = []
        params: list = []
        if query:
            terms = _query_terms(query)
            text_clauses = []
            for term in terms:
                text_clauses.append("(card_text LIKE ? OR summary LIKE ?)")
                like = f"%{term}%"
                params.extend([like, like])
            clauses.append(f"({' OR '.join(text_clauses)})")
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        if source_agent:
            clauses.append("source_agent = ?")
            params.append(source_agent)
        if access_levels:
            placeholders = ",".join("?" for _ in access_levels)
            clauses.append(f"access_level IN ({placeholders})")
            params.extend(access_levels)
        for tag in tags:
            clauses.append("tags LIKE ?")
            params.append(f"%{tag}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        conn = self._get_conn()
        try:
            rows = conn.execute(
                f"""SELECT * FROM memory_cards
                    {where}
                    ORDER BY created_at DESC, memory_id ASC
                    LIMIT ?""",
                params,
            ).fetchall()
            return [self._row_to_card(row) for row in rows]
        finally:
            conn.close()

    async def get_raw(self, raw_memory_id: str, user_id: str = "") -> dict | None:
        return await asyncio.to_thread(self._get_raw_sync, raw_memory_id, user_id)

    def _get_raw_sync(self, raw_memory_id: str, user_id: str = "") -> dict | None:
        conn = self._get_conn()
        try:
            if user_id:
                row = conn.execute(
                    "SELECT * FROM raw_memory WHERE memory_id=? AND user_id=?",
                    (raw_memory_id, user_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM raw_memory WHERE memory_id=?",
                    (raw_memory_id,),
                ).fetchone()
            if row is None:
                return None
            return self._row_to_raw(row)
        finally:
            conn.close()

    async def create_result_set(
        self,
        user_id: str,
        query_text: str,
        items: list[dict],
        metadata: dict | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._create_result_set_sync, user_id, query_text, items, metadata or {}
        )

    def _create_result_set_sync(
        self, user_id: str, query_text: str, items: list[dict], metadata: dict
    ) -> str:
        result_set_id = f"rs-{uuid.uuid4().hex[:12]}"
        memory_ids = [item["memory_id"] if isinstance(item, dict) else str(item) for item in items]
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO result_sets
                   (result_set_id, user_id, query_text, memory_ids, cursor,
                    created_at, expires_at, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result_set_id,
                    user_id or "",
                    query_text or "",
                    json.dumps(memory_ids, ensure_ascii=False),
                    0,
                    _now_sqlite(),
                    _expires_sqlite(),
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )
            conn.commit()
            return result_set_id
        finally:
            conn.close()

    async def expand_result(
        self, result_set_id: str, result_index: int, user_id: str = ""
    ) -> dict | None:
        return await asyncio.to_thread(
            self._expand_result_sync, result_set_id, result_index, user_id
        )

    def _expand_result_sync(
        self, result_set_id: str, result_index: int, user_id: str = ""
    ) -> dict | None:
        if result_index < 1:
            return None
        result_set = self._get_result_set_sync(result_set_id, user_id)
        if result_set is None:
            return None
        offset = result_index - 1
        memory_ids = result_set["memory_ids"]
        if offset >= len(memory_ids):
            return None

        memory_id = memory_ids[offset]
        card = self._get_card_sync(memory_id)
        if card is None:
            return None
        raw_memory_id = card.get("raw_memory_id") or memory_id
        raw = self._get_raw_sync(raw_memory_id, user_id=user_id)
        return {
            "result_set_id": result_set_id,
            "result_index": result_index,
            "memory_id": memory_id,
            "raw_memory_id": raw_memory_id,
            "content": (raw or {}).get("content", ""),
            "raw_memory": raw,
            "card": card,
            "_raw_route": "raw_memory" if raw is not None else "",
        }

    async def next_page(
        self, result_set_id: str, user_id: str = "", page_size: int = 5
    ) -> dict | None:
        return await asyncio.to_thread(self._next_page_sync, result_set_id, user_id, page_size)

    def _next_page_sync(
        self, result_set_id: str, user_id: str = "", page_size: int = 5
    ) -> dict | None:
        result_set = self._get_result_set_sync(result_set_id, user_id)
        if result_set is None:
            return None
        page_size = page_size if page_size > 0 else 5
        cursor = max(0, int(result_set.get("cursor") or 0))
        memory_ids = result_set["memory_ids"]
        next_cursor = min(len(memory_ids), cursor + page_size)
        page_ids = memory_ids[cursor:next_cursor]
        items = []
        for index, memory_id in enumerate(page_ids, start=cursor + 1):
            card = self._get_card_sync(memory_id)
            if card is None:
                continue
            card["_result_set_id"] = result_set_id
            card["_result_index"] = index
            items.append(card)

        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE result_sets SET cursor=? WHERE result_set_id=?",
                (next_cursor, result_set_id),
            )
            conn.commit()
        finally:
            conn.close()
        return {
            "result_set_id": result_set_id,
            "items": items,
            "next_cursor": next_cursor,
            "has_more": next_cursor < len(memory_ids),
        }

    async def get_latest_result_set_id(self, user_id: str) -> str | None:
        return await asyncio.to_thread(self._get_latest_result_set_id_sync, user_id)

    def _get_latest_result_set_id_sync(self, user_id: str) -> str | None:
        if not user_id:
            return None
        conn = self._get_conn()
        try:
            row = conn.execute(
                """SELECT result_set_id FROM result_sets
                   WHERE user_id=?
                   ORDER BY created_at DESC, result_set_id DESC LIMIT 1""",
                (user_id,),
            ).fetchone()
            return row["result_set_id"] if row else None
        finally:
            conn.close()

    async def append_working_memory(self, user_id: str, role: str, content: str) -> None:
        await asyncio.to_thread(self._append_working_memory_sync, user_id, role, content)

    def _append_working_memory_sync(self, user_id: str, role: str, content: str) -> None:
        if not user_id or not content:
            return
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO working_memory(user_id, role, content, ts) VALUES (?, ?, ?, ?)",
                (user_id, role, content[:500], _now_sqlite()),
            )
            conn.commit()
        finally:
            conn.close()

    async def get_working_memory(self, user_id: str, limit: int = 3) -> list[dict]:
        return await asyncio.to_thread(self._get_working_memory_sync, user_id, limit)

    def _get_working_memory_sync(self, user_id: str, limit: int = 3) -> list[dict]:
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
        entries = [dict(row) for row in rows]
        rounds = []
        index = 0
        while index < len(entries):
            entry = entries[index]
            if entry["role"] == "user":
                nxt = entries[index + 1] if index + 1 < len(entries) else None
                assistant = nxt["content"] if nxt and nxt["role"] == "assistant" else ""
                rounds.append({"user": entry["content"], "assistant": assistant, "ts": entry["ts"]})
                index += 2 if nxt and nxt["role"] == "assistant" else 1
            else:
                index += 1
        return rounds[-limit:] if len(rounds) > limit else rounds

    async def get_active_conversation_id(self, user_id: str) -> str:
        return await asyncio.to_thread(self._get_active_conversation_id_sync, user_id)

    def get_active_conversation_id_sync(self, user_id: str) -> str:
        return self._get_active_conversation_id_sync(user_id)

    def _get_active_conversation_id_sync(self, user_id: str) -> str:
        if not user_id:
            return ""
        conn = self._get_conn()
        try:
            row = conn.execute(
                """SELECT conversation_id FROM conversations
                   WHERE user_id=? AND status='active'
                   ORDER BY last_message_at DESC LIMIT 1""",
                (user_id,),
            ).fetchone()
            return row["conversation_id"] if row else ""
        finally:
            conn.close()

    def _get_result_set_sync(self, result_set_id: str, user_id: str = "") -> dict | None:
        conn = self._get_conn()
        try:
            if user_id:
                row = conn.execute(
                    "SELECT * FROM result_sets WHERE result_set_id=? AND user_id=?",
                    (result_set_id, user_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM result_sets WHERE result_set_id=?",
                    (result_set_id,),
                ).fetchone()
            if row is None:
                return None
            result_set = dict(row)
            try:
                result_set["memory_ids"] = json.loads(result_set.get("memory_ids") or "[]")
            except (json.JSONDecodeError, TypeError):
                result_set["memory_ids"] = []
            return result_set
        finally:
            conn.close()

    def _get_card_sync(self, memory_id: str, conn=None) -> dict | None:
        owns_conn = conn is None
        conn = conn or self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM memory_cards WHERE memory_id=?",
                (memory_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_card(row)
        finally:
            if owns_conn:
                conn.close()

    @staticmethod
    def _row_to_card(row) -> dict:
        card = dict(row)
        for key, fallback in (
            ("tags", []),
            ("source_refs", {}),
            ("score_metadata", {}),
        ):
            try:
                card[key] = json.loads(card.get(key) or json.dumps(fallback))
            except (json.JSONDecodeError, TypeError):
                card[key] = fallback
        return card

    @staticmethod
    def _row_to_raw(row) -> dict:
        raw = dict(row)
        try:
            raw["metadata"] = json.loads(raw.get("metadata") or "{}")
        except (json.JSONDecodeError, TypeError):
            raw["metadata"] = {}
        return raw


def _query_terms(query: str) -> list[str]:
    terms = [term for term in query.split() if term]
    return terms or [query]
