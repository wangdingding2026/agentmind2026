import pytest


class _TaskService:
    async def get_task_stats(self):
        return {
            "total": 10,
            "completed": 8,
            "failed": 2,
            "avg_execution_time_ms": 42,
        }

    async def get_recent_errors(self, limit=5):
        return [{"trace_id": "t-fail", "error_message": "timeout"}]


class _CapabilityRegistry:
    def list_profiles(self):
        return [
            {"agent_id": "a1", "healthy": True, "success_rate": 0.9},
            {"agent_id": "a2", "healthy": False, "success_rate": 0.5},
        ]


class _StrategyManager:
    def list_strategies(self):
        return [
            {"name": "explicit", "kind": "core", "enabled": True},
            {"name": "llm_routing", "kind": "core", "enabled": False},
        ]


class _AuditService:
    async def query_events(self, **kwargs):
        return [{"event_id": "e1", "module": "routing"}]


@pytest.mark.asyncio
async def test_control_plane_overview_service_reports_system_status_independent_of_agent_and_task_errors():
    from agentmind.services.control_plane_overview_service import ControlPlaneOverviewService

    service = ControlPlaneOverviewService(
        task_service=_TaskService(),
        capability_registry=_CapabilityRegistry(),
        strategy_manager=_StrategyManager(),
        audit_service=_AuditService(),
    )

    overview = await service.overview()

    assert overview["status"] == "healthy"
    assert overview["summary"] == {
        "agents_total": 2,
        "agents_healthy": 1,
        "tasks_total": 10,
        "tasks_completed": 8,
        "tasks_failed": 2,
        "avg_execution_time_ms": 42,
        "recent_audit_events": 1,
    }
    assert [agent["agent_id"] for agent in overview["agents"]] == ["a1", "a2"]
    assert [strategy["name"] for strategy in overview["strategies"]] == [
        "explicit",
        "llm_routing",
    ]
    assert overview["recent_errors"] == [
        {"trace_id": "t-fail", "error_message": "timeout"}
    ]
    assert overview["recent_audit_events"] == [{"event_id": "e1", "module": "routing"}]


@pytest.mark.asyncio
async def test_control_plane_overview_service_projects_service_status_shape():
    from agentmind.services.control_plane_overview_service import ControlPlaneOverviewService

    service = ControlPlaneOverviewService(
        task_service=_TaskService(),
        capability_registry=_CapabilityRegistry(),
        strategy_manager=_StrategyManager(),
        audit_service=_AuditService(),
    )

    status = await service.service_status()

    assert status == {
        "agents_total": 2,
        "agents_healthy": 1,
        "tasks_total": 10,
        "tasks_completed": 8,
        "tasks_failed": 2,
        "avg_execution_time_ms": 42,
    }
