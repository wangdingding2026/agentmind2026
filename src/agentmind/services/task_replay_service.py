from __future__ import annotations

from typing import Any

from agentmind.services.task_timeline_service import TaskTimelineService


class TaskReplayService:
    """Service-level replay boundary over persisted task timeline events."""

    def __init__(self, *, task_timeline_service=None):
        self._task_timeline_service = task_timeline_service or TaskTimelineService()

    async def replay(self, trace_id: str, limit: int = 100) -> dict[str, Any]:
        timeline = await self._task_timeline_service.timeline(
            trace_id,
            limit=limit,
        )
        found = bool(timeline.get("found"))
        return {
            "trace_id": timeline.get("trace_id", trace_id),
            "found": found,
            "event_count": timeline.get("event_count", 0),
            "source": "task_events",
            "replay_status": "available" if found else "missing",
            "timeline": timeline.get("timeline", []),
        }
