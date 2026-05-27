import json
import sqlite3

import pytest


@pytest.mark.asyncio
async def test_task_event_service_records_and_queries_ordered_events(tmp_path):
    from agentmind.services.task_event_service import TaskEventService

    service = TaskEventService(str(tmp_path / "trace.db"))

    first_id = await service.record_event(
        trace_id="t1",
        event_type="task_started",
        message="task started",
        payload={"source": "route"},
    )
    second_id = await service.record_event(
        trace_id="t1",
        event_type="agent_selected",
        seq=20,
        agent_id="a1",
        payload={"strategy": "explicit"},
    )
    await service.record_event(
        trace_id="t2",
        event_type="task_started",
        message="other task",
    )

    events = await service.query_events(trace_id="t1")

    assert [event["event_id"] for event in events] == [first_id, second_id]
    assert [event["event_type"] for event in events] == [
        "task_started",
        "agent_selected",
    ]
    assert events[0]["seq"] == 10
    assert events[0]["message"] == "task started"
    assert events[0]["payload"] == {"source": "route"}
    assert events[1]["seq"] == 20
    assert events[1]["agent_id"] == "a1"
    assert events[1]["payload"] == {"strategy": "explicit"}


@pytest.mark.asyncio
async def test_task_event_service_rejects_unknown_event_type(tmp_path):
    from agentmind.services.task_event_service import TaskEventService

    service = TaskEventService(str(tmp_path / "trace.db"))

    with pytest.raises(ValueError, match="unsupported task event type"):
        await service.record_event(trace_id="t1", event_type="unknown")


def test_task_events_are_persisted_as_json_payload(tmp_path):
    from agentmind.services.task_event_service import TaskEventService

    service = TaskEventService(str(tmp_path / "trace.db"))
    event_id = service._record_event_sync(
        trace_id="t1",
        event_type="partial_output",
        payload={"chunk_index": 1, "size": 42},
    )

    conn = sqlite3.connect(str(tmp_path / "trace.db"))
    try:
        row = conn.execute(
            "SELECT payload FROM task_events WHERE event_id=?",
            (event_id,),
        ).fetchone()
    finally:
        conn.close()

    assert json.loads(row[0]) == {"chunk_index": 1, "size": 42}


def test_task_event_service_is_exported_from_services_package():
    from agentmind.services import TaskEventService

    assert TaskEventService.__name__ == "TaskEventService"
