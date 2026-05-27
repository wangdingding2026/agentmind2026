import pytest


class _TaskTimelineService:
    def __init__(self):
        self.calls = []

    async def timeline(self, trace_id, limit=100):
        self.calls.append({"trace_id": trace_id, "limit": limit})
        if trace_id == "missing":
            return {
                "trace_id": trace_id,
                "found": False,
                "event_count": 0,
                "timeline": [],
            }
        return {
            "trace_id": trace_id,
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
                    "payload": {},
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


class _SparseTaskTimelineService:
    def __init__(self):
        self.calls = []

    async def timeline(self, trace_id, limit=100):
        self.calls.append({"trace_id": trace_id, "limit": limit})
        return {"timeline": []}


@pytest.mark.asyncio
async def test_task_replay_service_returns_service_level_replay_dto():
    from agentmind.services.task_replay_service import TaskReplayService

    timeline_service = _TaskTimelineService()
    service = TaskReplayService(task_timeline_service=timeline_service)

    replay = await service.replay("t1", limit=25)

    assert replay == {
        "trace_id": "t1",
        "found": True,
        "event_count": 2,
        "source": "task_events",
        "replay_status": "available",
        "limit": 25,
        "timeline": [
            {
                "event_id": "e1",
                "created_at": "2026-05-27 10:00:00",
                "event_type": "task_started",
                "seq": 10,
                "agent_id": "",
                "message": "task started",
                "payload": {},
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
    assert timeline_service.calls == [{"trace_id": "t1", "limit": 25}]


@pytest.mark.asyncio
async def test_task_replay_service_returns_missing_replay_dto():
    from agentmind.services.task_replay_service import TaskReplayService

    service = TaskReplayService(task_timeline_service=_TaskTimelineService())

    assert await service.replay("missing") == {
        "trace_id": "missing",
        "found": False,
        "event_count": 0,
        "source": "task_events",
        "replay_status": "missing",
        "limit": 100,
        "timeline": [],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("input_limit", "expected_limit"),
    [
        (0, 1),
        (-5, 1),
        (501, 500),
        ("7", 7),
        ("bad", 100),
        (None, 100),
    ],
)
async def test_task_replay_service_normalizes_limit(input_limit, expected_limit):
    from agentmind.services.task_replay_service import TaskReplayService

    timeline_service = _TaskTimelineService()
    service = TaskReplayService(task_timeline_service=timeline_service)

    replay = await service.replay("t1", limit=input_limit)

    assert replay["limit"] == expected_limit
    assert timeline_service.calls == [{"trace_id": "t1", "limit": expected_limit}]


@pytest.mark.asyncio
async def test_task_replay_service_stabilizes_sparse_timeline_response():
    from agentmind.services.task_replay_service import TaskReplayService

    timeline_service = _SparseTaskTimelineService()
    service = TaskReplayService(task_timeline_service=timeline_service)

    assert await service.replay("t1") == {
        "trace_id": "t1",
        "found": False,
        "event_count": 0,
        "source": "task_events",
        "replay_status": "missing",
        "limit": 100,
        "timeline": [],
    }
    assert timeline_service.calls == [{"trace_id": "t1", "limit": 100}]


@pytest.mark.asyncio
async def test_task_replay_service_preserves_timeline_service_order():
    from agentmind.services.task_replay_service import TaskReplayService

    timeline_service = _TaskTimelineService()
    service = TaskReplayService(task_timeline_service=timeline_service)

    replay = await service.replay("t1")

    assert [event["event_id"] for event in replay["timeline"]] == ["e1", "e2"]


def test_task_replay_service_is_exported_from_services_package():
    from agentmind.services import TaskReplayService

    assert TaskReplayService.__name__ == "TaskReplayService"
