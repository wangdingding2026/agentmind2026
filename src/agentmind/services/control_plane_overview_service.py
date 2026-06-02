from __future__ import annotations

from typing import Any

from agentmind.services.audit_service import AuditService
from agentmind.services.task_service import TaskService


class ControlPlaneOverviewService:
    """Aggregate control-plane status from service boundaries."""

    def __init__(
        self,
        *,
        task_service=None,
        capability_registry=None,
        strategy_manager=None,
        audit_service=None,
    ):
        self._task_service = task_service or TaskService()
        self._capability_registry = capability_registry
        self._strategy_manager = strategy_manager
        self._audit_service = audit_service or AuditService()

    async def overview(self) -> dict[str, Any]:
        stats = await self._task_service.get_task_stats()
        agents = self._agents()
        strategies = self._strategies()
        recent_errors = await self._task_service.get_recent_errors(limit=5)
        recent_audit_events = await self._audit_service.query_events(limit=10)
        summary = self._summary(stats, agents, recent_audit_events)
        return {
            "status": self._system_status(),
            "summary": summary,
            "agents": agents,
            "strategies": strategies,
            "recent_errors": recent_errors,
            "recent_audit_events": recent_audit_events,
        }

    async def service_status(self) -> dict[str, Any]:
        overview = await self.overview()
        summary = overview["summary"]
        return {
            "agents_total": summary["agents_total"],
            "agents_healthy": summary["agents_healthy"],
            "tasks_total": summary["tasks_total"],
            "tasks_completed": summary["tasks_completed"],
            "tasks_failed": summary["tasks_failed"],
            "avg_execution_time_ms": summary["avg_execution_time_ms"],
        }

    def _agents(self) -> list[dict[str, Any]]:
        if self._capability_registry is None:
            return []
        return self._capability_registry.list_profiles()

    def _strategies(self) -> list[dict[str, Any]]:
        if self._strategy_manager is None:
            return []
        return self._strategy_manager.list_strategies()

    def _summary(
        self,
        stats: dict[str, Any],
        agents: list[dict[str, Any]],
        recent_audit_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "agents_total": len(agents),
            "agents_healthy": sum(1 for agent in agents if agent.get("healthy")),
            "tasks_total": stats.get("total", 0),
            "tasks_completed": stats.get("completed", 0),
            "tasks_failed": stats.get("failed", 0),
            "avg_execution_time_ms": stats.get("avg_execution_time_ms", 0),
            "recent_audit_events": len(recent_audit_events),
        }

    def _system_status(self) -> str:
        return "healthy"
