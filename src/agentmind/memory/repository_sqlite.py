"""SQLite repository boundary for canonical memory tables."""

from __future__ import annotations

import asyncio
import gzip
import json
import math
import re
import sqlite3
import struct
import uuid
from datetime import datetime, timedelta, timezone

from agentmind.memory.dto import MemoryWriteCommand
from agentmind.memory.provider import (
    embedding_to_blob,
    generate_embedding_sync,
)
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

    def connect_sync(self) -> sqlite3.Connection:
        return self._get_conn()

    async def write_raw_and_card(self, command: MemoryWriteCommand) -> dict:
        return await asyncio.to_thread(self._write_raw_and_card_sync, command)

    def _write_raw_and_card_sync(self, command: MemoryWriteCommand) -> dict:
        memory_id = command.memory_id or f"mem-{uuid.uuid4().hex[:16]}"
        raw_memory_id = memory_id
        now = command.created_at or _now_sqlite()
        session_id = command.session_id or command.conversation_id
        tags_json = json.dumps(command.tags, ensure_ascii=False)
        metadata = json.dumps({
            "source_kind": command.source_kind,
            "parent_id": command.parent_id,
        }, ensure_ascii=False)
        card_text = f"{command.summary}\n\n{command.content}" if command.summary else command.content
        source_refs_data = {
            "raw_memory_id": raw_memory_id,
            "source_agent": command.source_agent,
            "source_task_id": command.source_task_id,
        }
        if command.parent_id:
            source_refs_data["parent_id"] = command.parent_id
        source_refs = json.dumps(source_refs_data, ensure_ascii=False)
        score_metadata = json.dumps({
            "importance": command.importance,
            "memory_type": command.memory_type,
            "content_hash": command.content_hash,
            "access_level": command.access_level,
            "embedding_model": command.embedding_model,
            "embedding_version": command.embedding_version,
        }, ensure_ascii=False)

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
                    card_text, source_refs, score_metadata, session_id, source_kind,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    memory_id,
                    raw_memory_id,
                    command.user_id,
                    command.summary,
                    command.source_agent,
                    command.source_task_id,
                    command.memory_type,
                    command.conversation_id,
                    command.importance,
                    tags_json,
                    command.access_level,
                    card_text,
                    source_refs,
                    score_metadata,
                    session_id,
                    command.source_kind,
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
        memory_types: list[str] | None = None,
        source_kinds: list[str] | None = None,
        conversation_id: str = "",
        exclude_conversation_id: str = "",
        time_range_start: str = "",
        time_range_end: str = "",
        limit: int = 10,
    ) -> list[dict]:
        return await asyncio.to_thread(
            self._search_cards_sync,
            query,
            user_id,
            tags or [],
            source_agent,
            access_levels or [],
            memory_types or [],
            source_kinds or [],
            conversation_id,
            exclude_conversation_id,
            time_range_start,
            time_range_end,
            limit,
        )

    async def read_conversation_turns(
        self,
        *,
        user_id: str,
        conversation_id: str = "",
        time_range_start: str = "",
        time_range_end: str = "",
        limit: int = 50,
        include_history_answers: bool = False,
    ) -> list[dict]:
        return await asyncio.to_thread(
            self._read_conversation_turns_sync,
            user_id,
            conversation_id,
            time_range_start,
            time_range_end,
            limit,
            include_history_answers,
        )

    def _read_conversation_turns_sync(
        self,
        user_id: str,
        conversation_id: str,
        time_range_start: str,
        time_range_end: str,
        limit: int,
        include_history_answers: bool,
    ) -> list[dict]:
        clauses = ["c.user_id = ?"]
        params: list = [user_id]
        if conversation_id:
            clauses.append("(c.conversation_id = ? OR c.session_id = ?)")
            params.extend([conversation_id, conversation_id])
        if time_range_start:
            clauses.append("c.created_at >= ?")
            params.append(time_range_start)
        if time_range_end:
            clauses.append("c.created_at <= ?")
            params.append(time_range_end)
        if not include_history_answers:
            clauses.append("c.source_kind != ?")
            params.append("conversation_history_answer")
        where = " AND ".join(clauses)
        params.append(limit)

        conn = self._get_conn()
        try:
            rows = conn.execute(
                f"""SELECT c.memory_id, c.summary, c.source_agent, c.source_kind,
                           c.conversation_id, c.created_at,
                           r.content AS question
                    FROM memory_cards c
                    JOIN raw_memory r ON r.memory_id = c.raw_memory_id
                    WHERE {where}
                    ORDER BY c.created_at ASC, c.memory_id ASC
                    LIMIT ?""",
                params,
            ).fetchall()
        finally:
            conn.close()

        import re as _re
        results = []
        for row in rows:
            answer = (row["summary"] or "").strip()
            answer = _re.sub(r'^\[[^\]]+\]\s*', '', answer)
            results.append({
                "memory_id": row["memory_id"],
                "created_at": row["created_at"],
                "conversation_id": row["conversation_id"],
                "source_agent": row["source_agent"],
                "source_kind": row["source_kind"],
                "question": (row["question"] or "").strip(),
                "answer": answer,
            })
        return results

    async def get_recent_cards(
        self,
        user_id: str,
        access_levels: list[str] | None = None,
        exclude_conversation_id: str = "",
        limit: int = 10,
    ) -> list[dict]:
        return await asyncio.to_thread(
            self._get_recent_cards_sync,
            user_id,
            access_levels or [],
            exclude_conversation_id,
            limit,
        )

    def _search_cards_sync(
        self,
        query: str,
        user_id: str,
        tags: list[str],
        source_agent: str,
        access_levels: list[str],
        memory_types: list[str],
        source_kinds: list[str],
        conversation_id: str,
        exclude_conversation_id: str,
        time_range_start: str,
        time_range_end: str,
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
        if memory_types:
            placeholders = ",".join("?" for _ in memory_types)
            clauses.append(f"memory_type IN ({placeholders})")
            params.extend(memory_types)
        if source_kinds:
            placeholders = ",".join("?" for _ in source_kinds)
            clauses.append(f"source_kind IN ({placeholders})")
            params.extend(source_kinds)
        if conversation_id:
            clauses.append("(conversation_id = ? OR session_id = ?)")
            params.extend([conversation_id, conversation_id])
        if exclude_conversation_id:
            clauses.append("(conversation_id != ? AND session_id != ?)")
            params.extend([exclude_conversation_id, exclude_conversation_id])
        if time_range_start:
            clauses.append("created_at >= ?")
            params.append(time_range_start)
        if time_range_end:
            clauses.append("created_at <= ?")
            params.append(time_range_end)
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
            cards = [self._row_to_card(row) for row in rows]
            for card in cards:
                card["_score"] = self._score_card(card, query)
                card["_route"] = "memory_cards"
            cards.sort(
                key=lambda item: (
                    -item["_score"],
                    item.get("memory_id", ""),
                )
            )
            return cards[:limit]
        finally:
            conn.close()

    def _get_recent_cards_sync(
        self,
        user_id: str,
        access_levels: list[str],
        exclude_conversation_id: str,
        limit: int,
    ) -> list[dict]:
        clauses = []
        params: list = []
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        if access_levels:
            placeholders = ",".join("?" for _ in access_levels)
            clauses.append(f"access_level IN ({placeholders})")
            params.extend(access_levels)
        if exclude_conversation_id:
            clauses.append("(conversation_id != ? AND session_id != ?)")
            params.extend([exclude_conversation_id, exclude_conversation_id])
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
            cards = [self._row_to_card(row) for row in rows]
            for card in cards:
                card["_score"] = self._score_card(card, "")
                card["_route"] = "memory_cards"
            return cards
        finally:
            conn.close()

    async def get_stats(self) -> dict:
        return await asyncio.to_thread(self._get_stats_sync)

    def _get_stats_sync(self) -> dict:
        conn = self._get_conn()
        try:
            total = conn.execute("SELECT COUNT(*) as cnt FROM memory_cards").fetchone()["cnt"]
            with_embedding = conn.execute(
                "SELECT COUNT(*) as cnt FROM memory_vectors"
            ).fetchone()["cnt"]
            by_source = {
                (row["source_agent"] or "unknown"): row["cnt"]
                for row in conn.execute(
                    "SELECT source_agent, COUNT(*) as cnt FROM memory_cards GROUP BY source_agent"
                ).fetchall()
            }
            by_type = {
                (row["memory_type"] or "episodic"): row["cnt"]
                for row in conn.execute(
                    "SELECT memory_type, COUNT(*) as cnt FROM memory_cards GROUP BY memory_type"
                ).fetchall()
            }
            by_access = {
                (row["access_level"] or "shared"): row["cnt"]
                for row in conn.execute(
                    "SELECT access_level, COUNT(*) as cnt FROM memory_cards GROUP BY access_level"
                ).fetchall()
            }
            latest = conn.execute(
                "SELECT created_at FROM memory_cards ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            return {
                "total": total,
                "by_source_agent": by_source,
                "by_type": by_type,
                "by_access_level": by_access,
                "by_heat": {"hot": 0, "warm": 0, "cold": total},
                "latest_at": latest["created_at"] if latest else None,
                "vector_search_enabled": bool(with_embedding),
                "with_embedding": with_embedding,
            }
        finally:
            conn.close()

    async def cleanup_memory(self, retention_days: int = 30) -> int:
        return await asyncio.to_thread(self._cleanup_memory_sync, retention_days)

    def _cleanup_memory_sync(self, retention_days: int = 30) -> int:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT memory_id, raw_memory_id FROM memory_cards WHERE created_at <= datetime(?, ?)",
                (_now_sqlite(), f"-{retention_days} days"),
            ).fetchall()
            if not rows:
                return 0
            for row in rows:
                self._delete_card_and_raw_sync(row["memory_id"], row["raw_memory_id"], conn)
            conn.commit()
            return len(rows)
        finally:
            conn.close()

    async def delete(self, memory_id: str) -> bool:
        return await asyncio.to_thread(self._delete_sync, memory_id)

    def _delete_sync(self, memory_id: str) -> bool:
        conn = self._get_conn()
        try:
            card = self._get_card_sync(memory_id, conn=conn)
            raw_memory_id = (card or {}).get("raw_memory_id") or memory_id
            self._delete_card_and_raw_sync(memory_id, raw_memory_id, conn)
            conn.commit()
            return True
        finally:
            conn.close()

    def _delete_card_and_raw_sync(self, memory_id: str, raw_memory_id: str, conn) -> None:
        conn.execute(
            "DELETE FROM memory_cards WHERE memory_id=? OR raw_memory_id=?",
            (memory_id, raw_memory_id),
        )
        conn.execute("DELETE FROM raw_memory WHERE memory_id=?", (raw_memory_id,))
        conn.execute("DELETE FROM result_sets WHERE memory_ids LIKE ?", (f"%{memory_id}%",))
        conn.execute("DELETE FROM memory_relations WHERE head_memory_id=? OR tail_memory_id=?", (memory_id, memory_id))
        conn.execute(
            """UPDATE core_memory SET status='invalidated', updated_at=?
               WHERE slot_value LIKE ?""",
            (_now_sqlite(), f"%{memory_id}%"),
        )

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

    async def get_card(self, memory_id: str) -> dict | None:
        return await asyncio.to_thread(self._get_card_sync, memory_id)

    async def list_peer_cards(self, user_id: str, exclude_memory_id: str = "") -> list[dict]:
        return await asyncio.to_thread(self._list_peer_cards_sync, user_id, exclude_memory_id)

    def _list_peer_cards_sync(self, user_id: str, exclude_memory_id: str = "") -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT * FROM memory_cards
                   WHERE user_id=? AND memory_id != ?
                   ORDER BY created_at DESC, memory_id ASC""",
                (user_id, exclude_memory_id),
            ).fetchall()
            return [self._row_to_card(row) for row in rows]
        finally:
            conn.close()

    async def mark_card_conflict(self, card: dict, other: dict, reason: str) -> None:
        await asyncio.to_thread(self._mark_card_conflict_sync, card, other, reason)

    def _mark_card_conflict_sync(self, card: dict, other: dict, reason: str) -> None:
        score_metadata = dict(card.get("score_metadata") or {})
        conflicts = score_metadata.setdefault("conflicts", [])
        if any(item.get("memory_id") == other["memory_id"] for item in conflicts):
            return
        conflicts.append({
            "memory_id": other["memory_id"],
            "reason": reason,
            "source_agent": other.get("source_agent", ""),
            "source_task_id": other.get("source_task_id", ""),
        })
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE memory_cards SET score_metadata=?, updated_at=datetime('now') WHERE memory_id=?",
                (json.dumps(score_metadata, ensure_ascii=False), card["memory_id"]),
            )
            conn.commit()
        finally:
            conn.close()

    async def confirm_core_memory(self, user_id: str, slot_key: str) -> bool:
        return await asyncio.to_thread(self._confirm_core_memory_sync, user_id, slot_key)

    def _confirm_core_memory_sync(self, user_id: str, slot_key: str) -> bool:
        conn = self._get_conn()
        try:
            conn.execute(
                """UPDATE core_memory SET status='confirmed', updated_at=?
                   WHERE user_id=? AND slot_key=? AND status='pending'""",
                (_now_sqlite(), user_id or "default", slot_key),
            )
            conn.commit()
            return conn.total_changes > 0
        finally:
            conn.close()

    async def read_core_memory(self, user_id: str) -> str:
        return await asyncio.to_thread(self._read_core_memory_sync, user_id)

    def read_core_memory_sync(self, user_id: str) -> str:
        return self._read_core_memory_sync(user_id)

    def _read_core_memory_sync(self, user_id: str) -> str:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT slot_key, slot_value FROM core_memory WHERE user_id=? AND status='confirmed'",
                (user_id or "default",),
            ).fetchall()
            parts = []
            for row in rows:
                try:
                    value = json.loads(row["slot_value"])
                    content = value.get("content", "") if isinstance(value, dict) else str(value)
                except (json.JSONDecodeError, TypeError):
                    content = row["slot_value"] or ""
                parts.append(f"[{row['slot_key']}] {content[:200]}")
            return "\n".join(parts)
        finally:
            conn.close()

    async def related_cards_for_query(
        self, query: str, user_id: str, limit: int = 5
    ) -> list[dict]:
        return await asyncio.to_thread(self._related_cards_for_query_sync, query, user_id, limit)

    def _related_cards_for_query_sync(self, query: str, user_id: str, limit: int = 5) -> list[dict]:
        if not query or not user_id:
            return []
        terms = _query_terms(query)
        relation_clauses = []
        params: list = [user_id]
        for term in terms:
            relation_clauses.append("(tail_entity LIKE ? OR relation LIKE ?)")
            like = f"%{term}%"
            params.extend([like, like])
        where = " OR ".join(relation_clauses)
        params.append(limit)
        conn = self._get_conn()
        try:
            rows = conn.execute(
                f"""SELECT DISTINCT c.* FROM memory_relations r
                    JOIN memory_cards c ON c.memory_id = r.head_memory_id
                    WHERE r.user_id=? AND ({where})
                    ORDER BY c.created_at DESC, c.memory_id ASC
                    LIMIT ?""",
                params,
            ).fetchall()
            cards = [self._row_to_card(row) for row in rows]
            for card in cards:
                card["_score"] = self._score_card(card, query) + 0.4
                card["_route"] = "memory_relations"
            return cards
        finally:
            conn.close()

    async def search_archive(
        self,
        *,
        query: str = "",
        user_id: str = "",
        memory_types: list | None = None,
        time_range_start: str = "",
        time_range_end: str = "",
        limit: int = 10,
    ) -> list[dict]:
        return await asyncio.to_thread(
            self._search_archive_sync,
            query,
            user_id,
            memory_types or [],
            time_range_start,
            time_range_end,
            limit,
        )

    async def archive_distilled_cards(self, retention_days: int = 90, limit: int = 1000) -> int:
        return await asyncio.to_thread(self._archive_distilled_cards_sync, retention_days, limit)

    def _archive_distilled_cards_sync(self, retention_days: int = 90, limit: int = 1000) -> int:
        conn = self._get_conn()
        archive_conn = self._get_archive_conn()
        if archive_conn is None:
            conn.close()
            return 0
        try:
            rows = conn.execute(
                """SELECT c.*, r.content AS raw_content
                   FROM memory_cards c
                   JOIN raw_memory r ON r.memory_id = c.raw_memory_id
                   WHERE json_extract(c.score_metadata, '$.distilled') = 1
                     AND c.created_at <= datetime(?, ?)
                   ORDER BY c.created_at ASC, c.memory_id ASC
                   LIMIT ?""",
                (_now_sqlite(), f"-{retention_days} days", limit),
            ).fetchall()
            if not rows:
                return 0
            archived_count = 0
            now = _now_sqlite()
            for row in rows:
                card = self._row_to_card(row)
                table_name = self._archive_table_for_created_at(card.get("created_at", ""))
                self._ensure_archive_table(archive_conn, table_name)
                compressed = gzip.compress((row["raw_content"] or "").encode("utf-8"))
                archive_conn.execute(
                    f"""INSERT OR REPLACE INTO {table_name}
                       (memory_id, user_id, memory_type, content_compressed, summary,
                        importance, original_created_at, archived_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        card["memory_id"],
                        card.get("user_id", ""),
                        card.get("memory_type", "episodic"),
                        compressed,
                        (card.get("summary", "") or "")[:1000],
                        card.get("importance", 0.5),
                        card.get("created_at", ""),
                        now,
                    ),
                )
                self._delete_card_and_raw_sync(card["memory_id"], card.get("raw_memory_id", ""), conn)
                archived_count += 1
            archive_conn.commit()
            conn.commit()
            return archived_count
        finally:
            archive_conn.close()
            conn.close()

    @staticmethod
    def _archive_table_for_created_at(created_at: str) -> str:
        try:
            dt = datetime.strptime(created_at[:10], "%Y-%m-%d")
            return f"archive_{dt.year}_{dt.month:02d}"
        except (ValueError, TypeError):
            return "archive_default"

    @staticmethod
    def _ensure_archive_table(conn: sqlite3.Connection, table_name: str) -> None:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                memory_id TEXT PRIMARY KEY,
                user_id TEXT,
                memory_type TEXT,
                content_compressed BLOB,
                summary TEXT,
                importance REAL,
                original_created_at TEXT,
                archived_at TEXT NOT NULL
            )
        """)

    async def rebuild_vector_index(
        self, *, target_version: int, model: str = "", limit: int = 100
    ) -> int:
        return await asyncio.to_thread(
            self._rebuild_vector_index_sync, target_version, model, limit
        )

    def _rebuild_vector_index_sync(
        self, target_version: int, model: str = "", limit: int = 100
    ) -> int:
        if target_version <= 0 or limit <= 0:
            return 0
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT c.memory_id, c.user_id, r.content, c.summary, c.card_text
                   FROM memory_cards c
                   JOIN raw_memory r ON r.memory_id = c.raw_memory_id
                   LEFT JOIN memory_vectors v ON v.memory_id = c.memory_id
                   WHERE v.memory_id IS NULL
                      OR v.version < ?
                      OR (? != '' AND v.model != ?)
                   ORDER BY c.created_at ASC, c.memory_id ASC
                   LIMIT ?""",
                (target_version, model, model, limit),
            ).fetchall()
            rebuilt = 0
            for row in rows:
                text = "\n\n".join(
                    part for part in [row["summary"], row["content"]]
                    if part
                ) or row["card_text"] or ""
                embedding = generate_embedding_sync(text)
                if not embedding:
                    continue
                self._write_vector_embedding_sync(
                    [row["memory_id"]],
                    embedding_to_blob(embedding),
                    model=model,
                    version=target_version,
                    dimension=len(embedding),
                    conn=conn,
                )
                rebuilt += 1
            conn.commit()
            return rebuilt
        finally:
            conn.close()

    def _search_archive_sync(
        self,
        query: str,
        user_id: str,
        memory_types: list,
        time_range_start: str,
        time_range_end: str,
        limit: int,
    ) -> list[dict]:
        if not user_id:
            return []
        conn = self._get_archive_conn()
        if conn is None:
            return []
        try:
            rows = []
            for table_name in self._archive_table_names(conn):
                rows.extend(
                    self._search_archive_table(
                        conn,
                        table_name,
                        query,
                        user_id,
                        memory_types,
                        time_range_start,
                        time_range_end,
                        limit,
                    )
                )
            rows.sort(
                key=lambda item: (
                    item.get("original_created_at", ""),
                    item.get("memory_id", ""),
                ),
                reverse=True,
            )
            return rows[:limit]
        finally:
            conn.close()

    def _get_archive_conn(self) -> sqlite3.Connection | None:
        archive_path = self._db_path.replace("memory.db", "archive.db")
        try:
            conn = sqlite3.connect(archive_path, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000")
            return conn
        except sqlite3.Error:
            return None

    def _archive_table_names(self, conn: sqlite3.Connection) -> list[str]:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'archive_%'"
        ).fetchall()
        return [row["name"] for row in rows if re.match(r"^archive_[A-Za-z0-9_]+$", row["name"])]

    def _search_archive_table(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        query: str,
        user_id: str,
        memory_types: list,
        time_range_start: str,
        time_range_end: str,
        limit: int,
    ) -> list[dict]:
        where = ["1=1", "user_id = ?"]
        params = [user_id]
        if memory_types:
            type_values = [mt.value if hasattr(mt, "value") else str(mt) for mt in memory_types]
            placeholders = ",".join("?" for _ in type_values)
            where.append(f"memory_type IN ({placeholders})")
            params.extend(type_values)
        if time_range_start:
            where.append("original_created_at >= ?")
            params.append(time_range_start)
        if time_range_end:
            where.append("original_created_at <= ?")
            params.append(time_range_end)
        sql = f"""SELECT * FROM {table_name}
               WHERE {' AND '.join(where)}
               ORDER BY original_created_at DESC, memory_id ASC
               LIMIT ?"""
        rows = conn.execute(sql, params + [limit * 3]).fetchall()
        archive_rows = [self._row_to_archive(row, table_name) for row in rows]
        if query:
            terms = _query_terms(query)
            archive_rows = [
                row for row in archive_rows
                if any(term in (row.get("summary", "") + "\n" + row.get("content", "")) for term in terms)
            ]
        return archive_rows

    @staticmethod
    def _row_to_archive(row, table_name: str) -> dict:
        d = dict(row)
        compressed = d.pop("content_compressed", b"")
        try:
            content = gzip.decompress(compressed).decode("utf-8")
        except Exception:
            content = ""
        d["content"] = content
        d["archive_table"] = table_name
        d["created_at"] = d.get("original_created_at", "")
        d["_route"] = "archive"
        return d

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
        raw_route = "raw_memory" if raw is not None else ""
        if raw is None:
            raw = self._get_archived_memory_sync(raw_memory_id, user_id=user_id)
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

    def _get_archived_memory_sync(self, memory_id: str, user_id: str = "") -> dict | None:
        if not memory_id or not user_id:
            return None
        conn = self._get_archive_conn()
        if conn is None:
            return None
        try:
            for table_name in self._archive_table_names(conn):
                row = conn.execute(
                    f"SELECT * FROM {table_name} WHERE memory_id=? AND user_id=? LIMIT 1",
                    (memory_id, user_id),
                ).fetchone()
                if row is not None:
                    return self._row_to_archive(row, table_name)
            return None
        finally:
            conn.close()

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

    def append_working_memory_sync(self, user_id: str, role: str, content: str) -> None:
        self._append_working_memory_sync(user_id, role, content)

    def _append_working_memory_sync(self, user_id: str, role: str, content: str) -> None:
        if not user_id or not content:
            return
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO working_memory(user_id, role, content, ts) VALUES (?, ?, ?, ?)",
                (user_id, role, content[:500], _now_sqlite()),
            )
            rows = conn.execute(
                """SELECT id FROM working_memory
                   WHERE user_id=? ORDER BY id DESC LIMIT -1 OFFSET ?""",
                (user_id, 20),
            ).fetchall()
            if rows:
                old_ids = [row["id"] for row in rows]
                placeholders = ",".join("?" for _ in old_ids)
                conn.execute(f"DELETE FROM working_memory WHERE id IN ({placeholders})", old_ids)
            conn.commit()
        finally:
            conn.close()

    async def get_working_memory(self, user_id: str, limit: int = 3) -> list[dict]:
        return await asyncio.to_thread(self._get_working_memory_sync, user_id, limit)

    def get_working_memory_sync(self, user_id: str, limit: int = 3) -> list[dict]:
        return self._get_working_memory_sync(user_id, limit)

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

    async def ensure_active_session(self, user_id: str) -> tuple[str, bool]:
        return await asyncio.to_thread(self._ensure_active_session_sync, user_id)

    def ensure_active_session_sync(self, user_id: str) -> tuple[str, bool]:
        return self._ensure_active_session_sync(user_id)

    def _ensure_active_session_sync(self, user_id: str) -> tuple[str, bool]:
        if not user_id:
            return "", False
        current = self._get_active_session_sync(user_id)
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

    async def consume_force_new(self, user_id: str) -> bool:
        return await asyncio.to_thread(self._consume_force_new_sync, user_id)

    def _consume_force_new_sync(self, user_id: str) -> bool:
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

    async def new_session(self, user_id: str) -> str:
        return await asyncio.to_thread(self._new_session_sync, user_id)

    def _new_session_sync(self, user_id: str) -> str:
        if not user_id:
            return ""
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        conn = self._get_conn()
        try:
            active = self._get_active_conversation_id_sync(user_id)
            if active:
                conn.execute(
                    "UPDATE conversations SET status='closed', last_message_at=? WHERE conversation_id=?",
                    (_now_sqlite(), active),
                )
            conn.execute(
                """INSERT INTO session_state(user_id, session_id, force_new_next, updated_at)
                   VALUES (?, ?, 1, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     session_id=excluded.session_id,
                     force_new_next=1,
                     updated_at=excluded.updated_at""",
                (user_id, sid, _now_sqlite()),
            )
            conn.execute("DELETE FROM working_memory WHERE user_id=?", (user_id,))
            conn.commit()
            return sid
        finally:
            conn.close()

    def get_active_session_sync(self, user_id: str) -> str | None:
        return self._get_active_session_sync(user_id)

    def _get_active_session_sync(self, user_id: str) -> str | None:
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

    def clear_working_memory_sync(self, user_id: str) -> None:
        if not user_id:
            return
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM working_memory WHERE user_id=?", (user_id,))
            conn.commit()
        finally:
            conn.close()

    async def find_or_create_conversation(
        self, user_id: str, content: str, force_new: bool = False
    ) -> str:
        return await asyncio.to_thread(
            self._find_or_create_conversation_sync, user_id, content, force_new
        )

    def _find_or_create_conversation_sync(
        self, user_id: str, content: str, force_new: bool = False
    ) -> str:
        if not user_id:
            return ""
        conn = self._get_conn()
        try:
            if not force_new:
                row = conn.execute(
                    """SELECT conversation_id FROM conversations
                       WHERE user_id=? AND status='active'
                         AND last_message_at >= datetime('now', '-30 minutes')
                       ORDER BY last_message_at DESC LIMIT 1""",
                    (user_id,),
                ).fetchone()
                if row:
                    conv_id = row["conversation_id"]
                    conn.execute(
                        "UPDATE conversations SET last_message_at=?, message_count=message_count+1 WHERE conversation_id=?",
                        (_now_sqlite(), conv_id),
                    )
                    conn.commit()
                    return conv_id
            conv_id = f"conv-{uuid.uuid4().hex[:12]}"
            now = _now_sqlite()
            conn.execute(
                """INSERT OR IGNORE INTO conversations
                   (conversation_id, user_id, first_message_at, last_message_at, status)
                   VALUES (?, ?, ?, ?, 'active')""",
                (conv_id, user_id, now, now),
            )
            conn.commit()
            return conv_id
        finally:
            conn.close()

    async def write_vector_embedding(
        self,
        memory_ids: list[str],
        embedding_blob: bytes,
        *,
        model: str = "",
        version: int = 1,
        dimension: int = 0,
    ) -> None:
        await asyncio.to_thread(
            self._write_vector_embedding_sync,
            memory_ids,
            embedding_blob,
            model,
            version,
            dimension,
            None,
        )

    def _write_vector_embedding_sync(
        self,
        memory_ids: list[str],
        embedding_blob: bytes,
        model: str = "",
        version: int = 1,
        dimension: int = 0,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        if not memory_ids or not embedding_blob:
            return
        resolved_dimension = dimension or _embedding_blob_dimension(embedding_blob)
        owns_conn = conn is None
        conn = conn or self._get_conn()
        try:
            now = _now_sqlite()
            for memory_id in memory_ids:
                row = conn.execute(
                    "SELECT user_id FROM memory_cards WHERE memory_id=?",
                    (memory_id,),
                ).fetchone()
                if row is None:
                    continue
                conn.execute(
                    """INSERT INTO memory_vectors
                       (memory_id, user_id, embedding, dimension, model, version, backend, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(memory_id) DO UPDATE SET
                           user_id=excluded.user_id,
                           embedding=excluded.embedding,
                           dimension=excluded.dimension,
                           model=excluded.model,
                           version=excluded.version,
                           backend=excluded.backend,
                           updated_at=excluded.updated_at""",
                    (
                        memory_id,
                        row["user_id"],
                        embedding_blob,
                        resolved_dimension,
                        model,
                        version,
                        self._vector_backend(),
                        now,
                    ),
                )
            if owns_conn:
                conn.commit()
        finally:
            if owns_conn:
                conn.close()

    async def search_vector(
        self,
        *,
        query_embedding: list[float],
        user_id: str = "",
        access_levels: list[str] | None = None,
        memory_types: list[str] | None = None,
        source_kinds: list[str] | None = None,
        exclude_conversation_id: str = "",
        limit: int = 10,
    ) -> list[dict]:
        return await asyncio.to_thread(
            self._search_vector_sync,
            query_embedding,
            user_id,
            access_levels or [],
            memory_types or [],
            source_kinds or [],
            exclude_conversation_id,
            limit,
        )

    def _search_vector_sync(
        self,
        query_embedding: list[float],
        user_id: str,
        access_levels: list[str],
        memory_types: list[str],
        source_kinds: list[str],
        exclude_conversation_id: str,
        limit: int,
    ) -> list[dict]:
        if not query_embedding or limit <= 0:
            return []
        clauses = ["v.dimension = ?"]
        params: list = [len(query_embedding)]
        if user_id:
            clauses.append("c.user_id = ?")
            params.append(user_id)
        if access_levels:
            placeholders = ",".join("?" for _ in access_levels)
            clauses.append(f"c.access_level IN ({placeholders})")
            params.extend(access_levels)
        if memory_types:
            placeholders = ",".join("?" for _ in memory_types)
            clauses.append(f"c.memory_type IN ({placeholders})")
            params.extend(memory_types)
        if source_kinds:
            placeholders = ",".join("?" for _ in source_kinds)
            clauses.append(f"c.source_kind IN ({placeholders})")
            params.extend(source_kinds)
        if exclude_conversation_id:
            clauses.append("(c.conversation_id != ? AND c.session_id != ?)")
            params.extend([exclude_conversation_id, exclude_conversation_id])
        where = " AND ".join(clauses)

        conn = self._get_conn()
        try:
            rows = conn.execute(
                f"""SELECT c.*, v.embedding
                    FROM memory_vectors v
                    JOIN memory_cards c ON c.memory_id = v.memory_id
                    WHERE {where}""",
                params,
            ).fetchall()
            cards = []
            for row in rows:
                card = self._row_to_card(row)
                candidate = _embedding_blob_to_list(row["embedding"])
                score = _cosine_similarity(query_embedding, candidate)
                if score <= 0:
                    continue
                card["_score"] = score
                card["_route"] = "memory_vectors"
                cards.append(card)
            cards.sort(
                key=lambda item: (
                    -item["_score"],
                    self._created_at_desc_sort_key(item.get("created_at", "")),
                    item.get("memory_id", ""),
                )
            )
            return cards[:limit]
        finally:
            conn.close()

    @staticmethod
    def _vector_backend() -> str:
        try:
            from agentmind.storage.db import is_vec_available

            return "sqlite-vec" if is_vec_available() else "sqlite"
        except Exception:
            return "sqlite"

    async def write_relations(
        self, user_id: str, relations: list[tuple[str, str, str, str, float]]
    ) -> None:
        await asyncio.to_thread(self._write_relations_sync, user_id, relations)

    def _write_relations_sync(
        self, user_id: str, relations: list[tuple[str, str, str, str, float]]
    ) -> None:
        if not relations:
            return
        now = _now_sqlite()
        conn = self._get_conn()
        try:
            for head, relation, target, tail_id, confidence in relations:
                conn.execute(
                    """INSERT OR IGNORE INTO memory_relations
                       (user_id, head_entity, relation, tail_entity,
                        head_memory_id, tail_memory_id, confidence, ts, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, head, relation, target, head, tail_id, confidence, now, now),
                )
            conn.commit()
        finally:
            conn.close()

    async def write_core_candidate(self, entry) -> None:
        await asyncio.to_thread(self._write_core_candidate_sync, entry)

    def _write_core_candidate_sync(self, entry) -> None:
        from agentmind.memory.components.core_memory_manager import CoreMemoryManager

        slot = CoreMemoryManager.guess_slot(entry.content, entry.summary)
        value = json.dumps({
            "content": entry.content[:500],
            "summary": entry.summary[:500],
            "source_memory_id": entry.memory_id,
            "importance": entry.importance,
        }, ensure_ascii=False)
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO core_memory
                   (user_id, slot_key, slot_value, byte_size, updated_at, updated_by, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
                (
                    entry.user_id or "default",
                    slot,
                    value,
                    len(value.encode("utf-8")),
                    _now_sqlite(),
                    entry.source_agent,
                ),
            )
            conn.commit()
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
        card.setdefault("source_kind", (card.get("source_refs") or {}).get("source_kind", "task"))
        return card

    def _score_card(self, card: dict, query: str) -> float:
        score = 0.0
        text = query.strip().lower()
        summary = (card.get("summary") or "").lower()
        card_text = (card.get("card_text") or "").lower()
        if text:
            for term in _query_terms(query):
                lowered = term.lower()
                if lowered in summary:
                    score += 1.0
                elif lowered in card_text:
                    score += 0.7
        else:
            score += 0.1
        try:
            score += 0.5 * float(card.get("importance") or 0.0)
        except (TypeError, ValueError):
            pass
        score += self._card_recency_tiebreaker(card.get("created_at", ""))
        return score

    @staticmethod
    def _card_recency_tiebreaker(created_at: str) -> float:
        try:
            date_part = created_at[:10].replace("-", "")
            return int(date_part) / 100_000_000_000
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _created_at_desc_sort_key(created_at: str) -> int:
        digits = "".join(ch for ch in str(created_at or "") if ch.isdigit())[:14]
        if not digits:
            return 0
        return -int(digits.ljust(14, "0"))

    @staticmethod
    def _row_to_raw(row) -> dict:
        raw = dict(row)
        try:
            raw["metadata"] = json.loads(raw.get("metadata") or "{}")
        except (json.JSONDecodeError, TypeError):
            raw["metadata"] = {}
        return raw


def _query_terms(query: str) -> list[str]:
    text = query.strip()
    if not text:
        return []
    terms = [text]
    terms.extend(re.findall(r"[A-Za-z0-9_./:-]+", text))
    terms.extend(re.findall(r"[\u4e00-\u9fff]{2,}", text))
    cjk_only = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    for width in (4, 3, 2):
        for index in range(max(0, len(cjk_only) - width + 1)):
            terms.append(cjk_only[index:index + width])
    return [term for term in dict.fromkeys(terms) if term]


def _embedding_blob_dimension(embedding_blob: bytes) -> int:
    if not embedding_blob:
        return 0
    return len(embedding_blob) // 4


def _embedding_blob_to_list(embedding_blob: bytes) -> list[float]:
    dimension = _embedding_blob_dimension(embedding_blob)
    if dimension <= 0:
        return []
    try:
        return list(struct.unpack(f"{dimension}f", embedding_blob))
    except struct.error:
        return []


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for left_value, right_value in zip(left, right):
        dot += left_value * right_value
        left_norm += left_value * left_value
        right_norm += right_value * right_value
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))
