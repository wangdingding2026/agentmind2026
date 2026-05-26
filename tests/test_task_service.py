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
