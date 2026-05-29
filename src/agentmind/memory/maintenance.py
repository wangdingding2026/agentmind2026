"""Maintenance helpers for legacy memory normalization."""

from __future__ import annotations

import json

from agentmind.memory.dto import MemoryAuditReport


class MemoryMaintenance:
    def __init__(self, repository):
        self.repository = repository

    def audit_legacy(self) -> MemoryAuditReport:
        conn = self.repository.connect_sync()
        try:
            memory_entries_count = _count(conn, "memory_entries")
            raw_count = _count(conn, "raw_memory")
            card_count = _count(conn, "memory_cards")
            missing_raw = conn.execute(
                """SELECT COUNT(*)
                   FROM memory_entries e
                   LEFT JOIN raw_memory r ON r.memory_id = e.memory_id
                   WHERE r.memory_id IS NULL"""
            ).fetchone()[0]
            missing_card = conn.execute(
                """SELECT COUNT(*)
                   FROM memory_entries e
                   LEFT JOIN memory_cards c ON c.raw_memory_id = e.memory_id
                   WHERE c.memory_id IS NULL"""
            ).fetchone()[0]
            orphan_raw = conn.execute(
                """SELECT COUNT(*)
                   FROM raw_memory r
                   LEFT JOIN memory_cards c ON c.raw_memory_id = r.memory_id
                   WHERE c.memory_id IS NULL"""
            ).fetchone()[0]
            orphan_card = conn.execute(
                """SELECT COUNT(*)
                   FROM memory_cards c
                   LEFT JOIN raw_memory r ON r.memory_id = c.raw_memory_id
                   WHERE r.memory_id IS NULL"""
            ).fetchone()[0]
            return MemoryAuditReport(
                memory_entries_count=memory_entries_count,
                raw_count=raw_count,
                card_count=card_count,
                missing_raw_for_entries=missing_raw,
                missing_card_for_entries=missing_card,
                orphan_raw=orphan_raw,
                orphan_card=orphan_card,
            )
        finally:
            conn.close()

    def normalize_legacy(self, apply: bool = False) -> MemoryAuditReport:
        if not apply:
            return self.audit_legacy()

        conn = self.repository.connect_sync()
        try:
            rows = conn.execute("SELECT * FROM memory_entries ORDER BY created_at, memory_id").fetchall()
            conn.execute("BEGIN")
            for row in rows:
                self._upsert_raw_and_card(conn, dict(row))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.audit_legacy()

    def drop_legacy_tables(self) -> None:
        conn = self.repository.connect_sync()
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'vec_memory%'"
            ).fetchall()
            conn.execute("DROP TABLE IF EXISTS memory_fts")
            for row in tables:
                conn.execute(f"DROP TABLE IF EXISTS {row['name']}")
            conn.execute("DROP TABLE IF EXISTS memory_entries")
            conn.commit()
        finally:
            conn.close()

    def _upsert_raw_and_card(self, conn, row: dict) -> None:
        memory_id = row.get("memory_id") or ""
        if not memory_id:
            return
        tags = _parse_tags(row.get("tags"))
        tags_json = json.dumps(tags, ensure_ascii=False)
        now = row.get("created_at") or ""
        memory_type = row.get("memory_type") or "episodic"
        summary = row.get("summary") or ""
        content = row.get("content") or ""
        metadata = json.dumps({
            "version": row.get("version") or 1,
            "access_level": row.get("access_level") or "shared",
            "content_hash": row.get("content_hash") or "",
            "parent_id": row.get("parent_id") or "",
        }, ensure_ascii=False)
        source_refs = json.dumps({
            "raw_memory_id": memory_id,
            "source_agent": row.get("source_agent") or "",
            "source_task_id": row.get("source_task_id") or "",
            "parent_id": row.get("parent_id") or "",
        }, ensure_ascii=False)
        score_metadata = json.dumps({
            "importance": _safe_float(row.get("importance"), 0.5),
            "memory_type": memory_type,
            "content_hash": row.get("content_hash") or "",
            "access_level": row.get("access_level") or "shared",
        }, ensure_ascii=False)
        card_text = f"{summary}\n\n{content}" if summary else content

        conn.execute(
            """INSERT OR IGNORE INTO raw_memory
               (memory_id, user_id, content, source_agent, source_task_id,
                memory_type, conversation_id, created_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                memory_id,
                row.get("user_id") or "",
                content,
                row.get("source_agent") or "",
                row.get("source_task_id") or "",
                memory_type,
                row.get("conversation_id") or "",
                now,
                metadata,
            ),
        )
        conn.execute(
            """INSERT OR IGNORE INTO memory_cards
               (memory_id, raw_memory_id, user_id, summary, source_agent, source_task_id,
                memory_type, conversation_id, importance, tags, access_level,
                card_text, source_refs, score_metadata, session_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                memory_id,
                memory_id,
                row.get("user_id") or "",
                summary,
                row.get("source_agent") or "",
                row.get("source_task_id") or "",
                memory_type,
                row.get("conversation_id") or "",
                _safe_float(row.get("importance"), 0.5),
                tags_json,
                row.get("access_level") or "shared",
                card_text,
                source_refs,
                score_metadata,
                row.get("conversation_id") or "",
                now,
                now,
            ),
        )


def _count(conn, table_name: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]


def _parse_tags(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _safe_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
