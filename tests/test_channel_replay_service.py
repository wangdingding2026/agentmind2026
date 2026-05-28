import pytest


class _TaskReplayService:
    def __init__(self, replay):
        self.replay_response = replay
        self.calls = []

    async def replay(self, trace_id, limit=100):
        self.calls.append({"trace_id": trace_id, "limit": limit})
        return self.replay_response


def _available_replay(event_count=3):
    return {
        "trace_id": "t1",
        "found": True,
        "event_count": event_count,
        "source": "task_events",
        "replay_status": "available",
        "limit": 10,
        "timeline": [
            {
                "created_at": "2026-05-28 10:00:00",
                "event_type": "task_started",
                "agent_id": "",
                "message": "task started",
            },
            {
                "created_at": "2026-05-28 10:00:01",
                "event_type": "agent_selected",
                "agent_id": "agent-a",
                "message": "",
            },
            {
                "created_at": "2026-05-28 10:00:02",
                "event_type": "completed",
                "agent_id": "agent-a",
                "message": "done",
            },
        ],
    }


@pytest.mark.asyncio
async def test_channel_replay_service_ignores_non_replay_messages():
    from agentmind.services.channel_replay_service import ChannelReplayService

    task_replay_service = _TaskReplayService(_available_replay())
    service = ChannelReplayService(task_replay_service=task_replay_service)

    result = await service.handle_text("hello")

    assert result is None
    assert task_replay_service.calls == []


@pytest.mark.asyncio
async def test_channel_replay_service_requires_explicit_trace_id():
    from agentmind.services.channel_replay_service import ChannelReplayService

    task_replay_service = _TaskReplayService(_available_replay())
    service = ChannelReplayService(task_replay_service=task_replay_service)

    result = await service.handle_text("/replay")

    assert result == "用法：/replay <trace_id>"
    assert task_replay_service.calls == []


@pytest.mark.asyncio
async def test_channel_replay_service_formats_available_replay_summary():
    from agentmind.services.channel_replay_service import ChannelReplayService

    task_replay_service = _TaskReplayService(_available_replay())
    service = ChannelReplayService(task_replay_service=task_replay_service, limit=10)

    result = await service.handle_text("/replay t1")

    assert result == (
        "任务回放 t1：available，3 个事件\n"
        "1. 2026-05-28 10:00:00 task_started - task started\n"
        "2. 2026-05-28 10:00:01 agent_selected [agent-a]\n"
        "3. 2026-05-28 10:00:02 completed [agent-a] - done"
    )
    assert task_replay_service.calls == [{"trace_id": "t1", "limit": 10}]


@pytest.mark.asyncio
async def test_channel_replay_service_formats_missing_replay_summary():
    from agentmind.services.channel_replay_service import ChannelReplayService

    task_replay_service = _TaskReplayService({
        "trace_id": "missing",
        "found": False,
        "event_count": 0,
        "source": "task_events",
        "replay_status": "missing",
        "limit": 10,
        "timeline": [],
    })
    service = ChannelReplayService(task_replay_service=task_replay_service, limit=10)

    result = await service.handle_text("/replay missing")

    assert result == "任务回放 missing：missing，未找到持久化任务事件。"
    assert task_replay_service.calls == [{"trace_id": "missing", "limit": 10}]


@pytest.mark.asyncio
async def test_channel_replay_service_bounds_summary_events():
    from agentmind.services.channel_replay_service import ChannelReplayService

    replay = _available_replay(event_count=3)
    task_replay_service = _TaskReplayService(replay)
    service = ChannelReplayService(
        task_replay_service=task_replay_service,
        limit=10,
        summary_event_limit=2,
    )

    result = await service.handle_text("/replay t1")

    assert "1. 2026-05-28 10:00:00 task_started - task started" in result
    assert "2. 2026-05-28 10:00:01 agent_selected [agent-a]" in result
    assert "还有 1 个事件未展示" in result
    assert "3. 2026-05-28 10:00:02 completed" not in result


def test_channel_replay_service_is_exported_from_services_package():
    from agentmind.services import ChannelReplayService

    assert ChannelReplayService.__name__ == "ChannelReplayService"
