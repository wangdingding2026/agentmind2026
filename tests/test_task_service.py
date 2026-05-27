import pytest

from agentmind.services.task_service import TaskService


@pytest.mark.asyncio
async def test_task_service_records_lifecycle(tmp_db):
    service = TaskService()

    await service.start_task("tr-service-1", "hello")
    await service.mark_routing("tr-service-1", matched_rule="rule", routed_agent="agent-a")
    await service.mark_executing("tr-service-1")
    await service.complete_task("tr-service-1", "agent-a", result="done", execution_time_ms=12)

    detail = await service.get_task_detail("tr-service-1")
    assert detail["trace_id"] == "tr-service-1"
    assert detail["status"] == "completed"
    assert detail["matched_rule"] == "rule"
    assert detail["routed_agent"] == "agent-a"
    assert detail["result_summary"] == "done"


@pytest.mark.asyncio
async def test_task_service_records_failure(tmp_db):
    service = TaskService()

    await service.start_task("tr-service-2", "hello")
    await service.fail_task("tr-service-2", "agent-a", error_message="boom", execution_time_ms=4)

    detail = await service.get_task_detail("tr-service-2")
    assert detail["status"] == "failed"
    assert detail["routed_agent"] == "agent-a"
    assert detail["error_message"] == "boom"


@pytest.mark.asyncio
async def test_storage_functions_delegate_to_task_service(tmp_db, monkeypatch):
    calls = []

    class FakeTaskService:
        async def start_task(self, trace_id, user_message):
            calls.append(("start", trace_id, user_message))

        async def update_task(self, trace_id, status, matched_rule=None, routed_agent=None):
            calls.append(("update", trace_id, status, matched_rule, routed_agent))

        async def end_task(
            self,
            trace_id,
            status,
            agent_id=None,
            execution_time_ms=None,
            error_message=None,
            result=None,
        ):
            calls.append(("end", trace_id, status, agent_id, execution_time_ms, result, error_message))

    monkeypatch.setattr("agentmind.storage.db.TaskService", FakeTaskService)

    from agentmind.storage.db import record_task_start, record_task_update, record_task_end

    await record_task_start("tr-compat", "msg")
    await record_task_update("tr-compat", "routing", matched_rule="rule", routed_agent="agent")
    await record_task_end("tr-compat", "completed", "agent", 5, result="ok")

    assert calls == [
        ("start", "tr-compat", "msg"),
        ("update", "tr-compat", "routing", "rule", "agent"),
        ("end", "tr-compat", "completed", "agent", 5, "ok", None),
    ]


class _TaskEventRecorder:
    def __init__(self):
        self.events = []

    async def record_event(self, **kwargs):
        self.events.append(kwargs)
        return f"event-{len(self.events)}"


class _FailingTaskEventRecorder:
    async def record_event(self, **kwargs):
        raise RuntimeError("event store unavailable")


@pytest.mark.asyncio
async def test_task_service_produces_timeline_events(tmp_db):
    event_service = _TaskEventRecorder()
    service = TaskService(task_event_service=event_service)

    await service.start_task("tr-events", "hello")
    await service.mark_routing("tr-events")
    await service.mark_routing("tr-events", matched_rule="rule", routed_agent="agent-a")
    await service.mark_executing("tr-events", routed_agent="agent-a")
    await service.complete_task("tr-events", "agent-a", result="done", execution_time_ms=12)

    assert [(event["event_type"], event["seq"]) for event in event_service.events] == [
        ("task_started", 10),
        ("routing_started", 20),
        ("agent_selected", 30),
        ("execution_started", 40),
        ("completed", 90),
    ]
    assert event_service.events[0]["message"] == "task started"
    assert event_service.events[0]["payload"] == {"user_message_length": 5}
    assert event_service.events[2]["agent_id"] == "agent-a"
    assert event_service.events[2]["payload"] == {"matched_rule": "rule"}
    assert event_service.events[3]["agent_id"] == "agent-a"
    assert event_service.events[4]["agent_id"] == "agent-a"
    assert event_service.events[4]["payload"] == {"execution_time_ms": 12}


@pytest.mark.asyncio
async def test_task_service_produces_failed_timeline_event(tmp_db):
    event_service = _TaskEventRecorder()
    service = TaskService(task_event_service=event_service)

    await service.start_task("tr-failed-events", "hello")
    await service.fail_task("tr-failed-events", "agent-a", error_message="boom", execution_time_ms=4)

    assert event_service.events[-1]["event_type"] == "failed"
    assert event_service.events[-1]["seq"] == 90
    assert event_service.events[-1]["agent_id"] == "agent-a"
    assert event_service.events[-1]["payload"] == {
        "execution_time_ms": 4,
        "has_error": True,
    }


@pytest.mark.asyncio
async def test_task_service_ignores_task_event_production_failures(tmp_db):
    service = TaskService(task_event_service=_FailingTaskEventRecorder())

    await service.start_task("tr-event-failure", "hello")
    await service.complete_task("tr-event-failure", "agent-a", result="done")

    detail = await service.get_task_detail("tr-event-failure")
    assert detail["status"] == "completed"
