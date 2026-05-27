from __future__ import annotations

from typing import Any

from agentmind.services.audit_service import AuditService
from agentmind.services.routing_explanation_service import RoutingExplanationService
from agentmind.services.task_service import TaskService


class TaskExplanationService:
    """Aggregate task lifecycle explanation data for the control plane."""

    def __init__(
        self,
        *,
        task_service=None,
        routing_explanation_service=None,
        audit_service=None,
    ):
        self._task_service = task_service or TaskService()
        self._routing_explanation_service = (
            routing_explanation_service or RoutingExplanationService()
        )
        self._audit_service = audit_service or AuditService()

    async def explain(self, trace_id: str) -> dict[str, Any]:
        task = await self._task_service.get_task_detail(trace_id)
        if task is None:
            return self._missing(trace_id)

        status = task.get("status", "unknown")
        stage = self._stage(task)
        failed = status == "failed"
        return {
            "trace_id": trace_id,
            "found": True,
            "status": status,
            "failed": failed,
            "stage": stage,
            "summary": self._summary(task, stage),
            "task": task,
            "routing": await self._routing_explanation_service.explain(trace_id),
            "audit_events": await self._audit_service.query_events(
                trace_id=trace_id,
                limit=20,
            ),
        }

    def _missing(self, trace_id: str) -> dict[str, Any]:
        return {
            "trace_id": trace_id,
            "found": False,
            "status": "missing",
            "failed": False,
            "stage": "unknown",
            "summary": "Task not found",
            "task": None,
            "routing": None,
            "audit_events": [],
        }

    def _stage(self, task: dict[str, Any]) -> str:
        status = task.get("status", "")
        if status in {"pending", "routing"}:
            return "routing"
        if status == "executing":
            return "execution"
        if status == "completed":
            return "completed"
        if status == "failed":
            return "execution" if task.get("routed_agent") else "routing"
        return "unknown"

    def _summary(self, task: dict[str, Any], stage: str) -> str:
        status = task.get("status", "")
        if status == "failed":
            message = task.get("error_message") or "unknown error"
            return f"Task failed during {stage}: {message}"
        if status == "completed":
            return "Task completed"
        return f"Task is {status or 'unknown'}"
