from __future__ import annotations

from typing import Any

from agentmind.services.task_event_service import TaskEventService


class TaskTimelineService:
    """Read-side task timeline DTO assembly."""

    def __init__(self, *, task_event_service=None):
        self._task_event_service = task_event_service or TaskEventService()

    async def timeline(self, trace_id: str, limit: int = 100) -> dict[str, Any]:
        events = await self._task_event_service.query_events(
            trace_id=trace_id,
            limit=limit,
        )
        timeline = [self._timeline_event(event) for event in events]
        return {
            "trace_id": trace_id,
            "found": bool(timeline),
            "event_count": len(timeline),
            "timeline": timeline,
        }

    def _timeline_event(self, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": event.get("event_id", ""),
            "created_at": event.get("created_at", ""),
            "event_type": event.get("event_type", ""),
            "seq": event.get("seq", 0),
            "agent_id": event.get("agent_id", ""),
            "message": event.get("message", ""),
            "payload": event.get("payload") or {},
        }
