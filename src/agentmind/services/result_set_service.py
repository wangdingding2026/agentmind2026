"""ResultSetService — persisted memory card result navigation."""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone


def _now_sqlite() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _expires_sqlite(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


class ResultSetService:
    """Persist ordered card search results and expand them through raw memory."""

    def __init__(self, store=None):
        if store is None:
            from agentmind.memory.sqlite_store import SqliteMemoryStore
            store = SqliteMemoryStore()
        self._store = store

    async def create_result_set(
        self,
        user_id: str,
        query_text: str,
        memory_ids: list[str],
        metadata: dict | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._create_result_set_sync,
            user_id,
            query_text,
            memory_ids,
            metadata or {},
        )

    def _create_result_set_sync(
        self,
        user_id: str,
        query_text: str,
        memory_ids: list[str],
        metadata: dict,
    ) -> str:
        result_set_id = f"rs-{uuid.uuid4().hex[:12]}"
        conn = self._store._get_conn()
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
            self._expand_result_sync,
            result_set_id,
            result_index,
            user_id,
        )

    async def next_page(
        self, result_set_id: str, user_id: str = "", page_size: int = 5
    ) -> dict | None:
        return await asyncio.to_thread(
            self._next_page_sync,
            result_set_id,
            user_id,
            page_size,
        )

    async def get_latest_result_set_id(self, user_id: str) -> str | None:
        return await asyncio.to_thread(self._get_latest_result_set_id_sync, user_id)

    def _get_latest_result_set_id_sync(self, user_id: str) -> str | None:
        if not user_id:
            return None
        conn = self._store._get_conn()
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

    def _next_page_sync(
        self, result_set_id: str, user_id: str = "", page_size: int = 5
    ) -> dict | None:
        if page_size <= 0:
            page_size = 5

        result_set = self._get_result_set_sync(result_set_id, user_id)
        if result_set is None:
            return None

        memory_ids = result_set["memory_ids"]
        cursor = max(0, int(result_set.get("cursor") or 0))
        next_cursor = min(len(memory_ids), cursor + page_size)
        page_ids = memory_ids[cursor:next_cursor]

        items = []
        for offset, memory_id in enumerate(page_ids, start=cursor + 1):
            card = self._store._get_memory_card_sync(memory_id)
            if card is None:
                continue
            item = dict(card)
            item["_result_set_id"] = result_set_id
            item["_result_index"] = offset
            items.append(item)

        conn = self._store._get_conn()
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

    def _expand_result_sync(
        self, result_set_id: str, result_index: int, user_id: str = ""
    ) -> dict | None:
        if result_index < 1:
            return None

        result_set = self._get_result_set_sync(result_set_id, user_id)
        if result_set is None:
            return None

        memory_ids = result_set["memory_ids"]
        offset = result_index - 1
        if offset >= len(memory_ids):
            return None

        memory_id = memory_ids[offset]
        card = self._store._get_memory_card_sync(memory_id)
        if card is None:
            return None

        raw_memory_id = card.get("raw_memory_id") or memory_id
        raw = self._store._get_raw_memory_sync(raw_memory_id)
        raw_route = "raw_memory"
        if raw is None:
            raw = self._store._get_archived_memory_sync(raw_memory_id, user_id=user_id)
            raw_route = "archive" if raw is not None else ""
        return {
            "result_set_id": result_set_id,
            "result_index": result_index,
            "memory_id": memory_id,
            "raw_memory_id": raw_memory_id,
            "content": (raw or {}).get("content", ""),
            "raw_memory": raw,
            "card": card,
            "_raw_route": raw_route,
        }

    def _get_result_set_sync(self, result_set_id: str, user_id: str = "") -> dict | None:
        conn = self._store._get_conn()
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
            d = dict(row)
            try:
                d["memory_ids"] = json.loads(d.get("memory_ids") or "[]")
            except (json.JSONDecodeError, TypeError):
                d["memory_ids"] = []
            try:
                d["metadata"] = json.loads(d.get("metadata") or "{}")
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = {}
            return d
        finally:
            conn.close()
