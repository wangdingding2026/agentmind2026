import pytest


class _TaskService:
    async def get_task_detail(self, trace_id):
        if trace_id == "missing":
            return None
        return {
            "trace_id": trace_id,
            "status": "failed",
            "user_message": "run job",
            "matched_rule": "explicit",
            "routed_agent": "a1",
            "execution_time_ms": 123,
            "error_message": "timeout",
            "result_summary": "",
        }


class _RoutingExplanationService:
    def __init__(self):
        self.calls = []

    async def explain(self, trace_id):
        self.calls.append(trace_id)
        return {
            "trace_id": trace_id,
            "found": True,
            "decision": {"agent_id": "a1", "strategy": "explicit"},
        }


class _AuditService:
    def __init__(self):
        self.calls = []

    async def query_events(self, **kwargs):
        self.calls.append(kwargs)
        return [{"event_id": "e1", "trace_id": "t1", "module": "execution"}]


@pytest.mark.asyncio
async def test_task_explanation_service_explains_execution_failure():
    from agentmind.services.task_explanation_service import TaskExplanationService

    routing_service = _RoutingExplanationService()
    audit_service = _AuditService()
    service = TaskExplanationService(
        task_service=_TaskService(),
        routing_explanation_service=routing_service,
        audit_service=audit_service,
    )

    explanation = await service.explain("t1")

    assert explanation["trace_id"] == "t1"
    assert explanation["found"] is True
    assert explanation["status"] == "failed"
    assert explanation["failed"] is True
    assert explanation["stage"] == "execution"
    assert explanation["summary"] == "Task failed during execution: timeout"
    assert explanation["task"]["error_message"] == "timeout"
    assert explanation["routing"]["decision"] == {"agent_id": "a1", "strategy": "explicit"}
    assert explanation["audit_events"] == [
        {"event_id": "e1", "trace_id": "t1", "module": "execution"}
    ]
    assert routing_service.calls == ["t1"]
    assert audit_service.calls == [{"trace_id": "t1", "limit": 20}]


@pytest.mark.asyncio
async def test_task_explanation_service_returns_stable_missing_task():
    from agentmind.services.task_explanation_service import TaskExplanationService

    service = TaskExplanationService(
        task_service=_TaskService(),
        routing_explanation_service=_RoutingExplanationService(),
        audit_service=_AuditService(),
    )

    explanation = await service.explain("missing")

    assert explanation == {
        "trace_id": "missing",
        "found": False,
        "status": "missing",
        "failed": False,
        "stage": "unknown",
        "summary": "Task not found",
        "task": None,
        "routing": None,
        "audit_events": [],
    }
