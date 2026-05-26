"""Memory card conflict detection."""

import asyncio
import json


class MemoryConflictDetector:
    """Detect conservative conflicts between memory cards."""

    def __init__(self, store):
        self._store = store

    async def detect_for_memory(self, memory_id: str) -> list[dict]:
        return await asyncio.to_thread(self._detect_for_memory_sync, memory_id)

    def _detect_for_memory_sync(self, memory_id: str) -> list[dict]:
        current = self._store._get_memory_card_sync(memory_id)
        if current is None:
            return []

        conflicts = []
        conn = self._store._get_conn()
        try:
            rows = conn.execute(
                """SELECT * FROM memory_cards
                   WHERE user_id=? AND memory_id != ?""",
                (current.get("user_id", ""), memory_id),
            ).fetchall()
            for row in rows:
                other = self._store._row_to_memory_card(row)
                reason = self._conflict_reason(current, other)
                if not reason:
                    continue
                self._mark_conflict(conn, current, other, reason)
                self._mark_conflict(conn, other, current, reason)
                conflicts.append({"memory_id": other["memory_id"], "reason": reason})
            conn.commit()
        finally:
            conn.close()
        return conflicts

    def _conflict_reason(self, current: dict, other: dict) -> str:
        if not self._overlapping_tags(current, other):
            return ""
        current_text = self._card_text(current)
        other_text = self._card_text(other)
        texts = (current_text, other_text)
        has_legacy = any("memory_entries" in text and "继续" in text for text in texts)
        has_cards = any("memory_cards" in text and "只搜" in text for text in texts)
        if has_legacy and has_cards:
            return "opposing_memory_architecture_recommendation"
        return ""

    @staticmethod
    def _overlapping_tags(current: dict, other: dict) -> bool:
        return bool(set(current.get("tags") or []) & set(other.get("tags") or []))

    @staticmethod
    def _card_text(card: dict) -> str:
        return f"{card.get('summary', '')}\n{card.get('card_text', '')}".lower()

    def _mark_conflict(self, conn, card: dict, other: dict, reason: str):
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
        conn.execute(
            "UPDATE memory_cards SET score_metadata=?, updated_at=datetime('now') WHERE memory_id=?",
            (json.dumps(score_metadata, ensure_ascii=False), card["memory_id"]),
        )
