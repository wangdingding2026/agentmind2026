"""Memory card conflict detection."""


class MemoryConflictDetector:
    """Detect conservative conflicts between memory cards."""

    def __init__(self, repository):
        self._repository = repository

    async def detect_for_memory(self, memory_id: str) -> list[dict]:
        current = await self._repository.get_card(memory_id)
        if current is None:
            return []

        conflicts = []
        peer_cards = await self._repository.list_peer_cards(
            current.get("user_id", ""), exclude_memory_id=memory_id
        )
        for other in peer_cards:
            reason = self._conflict_reason(current, other)
            if not reason:
                continue
            await self._repository.mark_card_conflict(current, other, reason)
            await self._repository.mark_card_conflict(other, current, reason)
            conflicts.append({"memory_id": other["memory_id"], "reason": reason})
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
