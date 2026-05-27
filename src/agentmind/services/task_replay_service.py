from __future__ import annotations

from typing import Any

from agentmind.services.task_timeline_service import TaskTimelineService


class TaskReplayService:
    """Service-level replay boundary over persisted task timeline events."""

    DEFAULT_LIMIT = 100
    MIN_LIMIT = 1
    MAX_LIMIT = 500

    def __init__(self, *, task_timeline_service=None):
        self._task_timeline_service = task_timeline_service or TaskTimelineService()

    async def replay(self, trace_id: str, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
        normalized_limit = self._normalize_limit(limit)
        timeline = await self._task_timeline_service.timeline(
            trace_id,
            limit=normalized_limit,
        )
        found = bool(timeline.get("found"))
        return {
            "trace_id": timeline.get("trace_id") or trace_id,
            "found": found,
            "event_count": timeline.get("event_count") or 0,
            "source": "task_events",
            "replay_status": "available" if found else "missing",
            "limit": normalized_limit,
            "timeline": timeline.get("timeline") or [],
        }

    def _normalize_limit(self, limit) -> int:
        try:
            normalized = int(limit)
        except (TypeError, ValueError):
            normalized = self.DEFAULT_LIMIT
        return max(self.MIN_LIMIT, min(self.MAX_LIMIT, normalized))
