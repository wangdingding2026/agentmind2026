import pytest


class _TaskEventService:
    def __init__(self):
        self.calls = []

    async def query_events(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["trace_id"] == "missing":
            return []
        return [
            {
                "event_id": "e1",
                "created_at": "2026-05-27 10:00:00",
                "trace_id": kwargs["trace_id"],
                "event_type": "task_started",
                "seq": 10,
                "agent_id": "",
                "message": "task started",
                "payload": {"user_message_length": 5},
            },
            {
                "event_id": "e2",
                "created_at": "2026-05-27 10:00:01",
                "trace_id": kwargs["trace_id"],
                "event_type": "completed",
                "seq": 90,
                "agent_id": "a1",
                "message": "",
                "payload": {"execution_time_ms": 12},
            },
        ]


@pytest.mark.asyncio
async def test_task_timeline_service_returns_stable_timeline_dto():
    from agentmind.services.task_timeline_service import TaskTimelineService

    task_event_service = _TaskEventService()
    service = TaskTimelineService(task_event_service=task_event_service)

    timeline = await service.timeline("t1")

    assert timeline == {
        "trace_id": "t1",
        "found": True,
        "event_count": 2,
        "timeline": [
            {
                "event_id": "e1",
                "created_at": "2026-05-27 10:00:00",
                "event_type": "task_started",
                "seq": 10,
                "agent_id": "",
                "message": "task started",
                "payload": {"user_message_length": 5},
            },
            {
                "event_id": "e2",
                "created_at": "2026-05-27 10:00:01",
                "event_type": "completed",
                "seq": 90,
                "agent_id": "a1",
                "message": "",
                "payload": {"execution_time_ms": 12},
            },
        ],
    }
    assert task_event_service.calls == [{"trace_id": "t1", "limit": 100}]


@pytest.mark.asyncio
async def test_task_timeline_service_returns_stable_missing_timeline():
    from agentmind.services.task_timeline_service import TaskTimelineService

    service = TaskTimelineService(task_event_service=_TaskEventService())

    assert await service.timeline("missing") == {
        "trace_id": "missing",
        "found": False,
        "event_count": 0,
        "timeline": [],
    }


def test_task_timeline_service_is_exported_from_services_package():
    from agentmind.services import TaskTimelineService

    assert TaskTimelineService.__name__ == "TaskTimelineService"
