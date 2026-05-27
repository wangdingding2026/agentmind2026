from __future__ import annotations

import asyncio
import logging

from agentmind.services.task_event_service import TaskEventService
from agentmind.storage import db as storage_db

logger = logging.getLogger("agentmind")


class TaskService:
    """Task lifecycle service.

    This first version wraps the existing storage implementation. It creates a
    stable service seam without changing the SQLite schema or public behavior.
    """

    def __init__(self, task_event_service=None):
        self._task_event_service = task_event_service or TaskEventService()

    async def start_task(self, trace_id: str, user_message: str):
        await asyncio.to_thread(storage_db._record_task_start_sync, trace_id, user_message)
        await self._record_task_event(
            trace_id=trace_id,
            event_type="task_started",
            seq=10,
            message="task started",
            payload={"user_message_length": len(user_message or "")},
        )

    async def update_task(
        self,
        trace_id: str,
        status: str,
        matched_rule: str | None = None,
        routed_agent: str | None = None,
    ):
        await asyncio.to_thread(
            storage_db._record_task_update_sync,
            trace_id,
            status,
            matched_rule,
            routed_agent,
        )
        if status == "routing" and routed_agent:
            await self._record_task_event(
                trace_id=trace_id,
                event_type="agent_selected",
                seq=30,
                agent_id=routed_agent,
                payload={"matched_rule": matched_rule or ""},
            )
        elif status == "routing":
            await self._record_task_event(
                trace_id=trace_id,
                event_type="routing_started",
                seq=20,
            )
        elif status == "executing":
            await self._record_task_event(
                trace_id=trace_id,
                event_type="execution_started",
                seq=40,
                agent_id=routed_agent or "",
            )

    async def mark_routing(
        self,
        trace_id: str,
        matched_rule: str | None = None,
        routed_agent: str | None = None,
    ):
        await self.update_task(trace_id, "routing", matched_rule, routed_agent)

    async def mark_executing(self, trace_id: str, routed_agent: str | None = None):
        await self.update_task(trace_id, "executing", routed_agent=routed_agent)

    async def end_task(
        self,
        trace_id: str,
        status: str,
        agent_id: str | None = None,
        execution_time_ms: int | None = None,
        error_message: str | None = None,
        result: str | None = None,
    ):
        await asyncio.to_thread(
            storage_db._save_result_sync,
            trace_id,
            status,
            agent_id,
            execution_time_ms,
            error_message,
            result,
        )
        if status in {"completed", "failed"}:
            payload = {"execution_time_ms": execution_time_ms}
            if status == "failed":
                payload["has_error"] = bool(error_message)
            await self._record_task_event(
                trace_id=trace_id,
                event_type=status,
                seq=90,
                agent_id=agent_id or "",
                payload=payload,
            )

    async def complete_task(
        self,
        trace_id: str,
        agent_id: str | None = None,
        result: str | None = None,
        execution_time_ms: int | None = None,
    ):
        await self.end_task(
            trace_id,
            "completed",
            agent_id,
            execution_time_ms=execution_time_ms,
            result=result,
        )

    async def fail_task(
        self,
        trace_id: str,
        agent_id: str | None = None,
        error_message: str | None = None,
        execution_time_ms: int | None = None,
    ):
        await self.end_task(
            trace_id,
            "failed",
            agent_id,
            execution_time_ms=execution_time_ms,
            error_message=error_message,
        )

    async def record_attached_turn(self, trace_id: str, user_message: str, agent_response: str):
        await asyncio.to_thread(
            storage_db._record_attached_turn_sync,
            trace_id,
            user_message,
            agent_response,
        )

    async def query_tasks(self, limit: int = 20, offset: int = 0, status: str | None = None) -> list[dict]:
        return await asyncio.to_thread(storage_db._query_tasks_sync, limit, offset, status)

    async def get_task_stats(self) -> dict:
        return await asyncio.to_thread(storage_db._get_task_stats_sync)

    async def get_task_detail(self, trace_id: str) -> dict | None:
        return await asyncio.to_thread(storage_db._get_task_detail_sync, trace_id)

    async def get_recent_errors(self, limit: int = 5) -> list[dict]:
        return await asyncio.to_thread(storage_db._get_recent_errors_sync, limit)

    async def get_metrics(self) -> dict:
        return await asyncio.to_thread(storage_db._get_metrics_sync)

    async def _record_task_event(
        self,
        *,
        trace_id: str,
        event_type: str,
        seq: int,
        agent_id: str = "",
        message: str = "",
        payload: dict | None = None,
    ) -> None:
        try:
            await self._task_event_service.record_event(
                trace_id=trace_id,
                event_type=event_type,
                seq=seq,
                agent_id=agent_id,
                message=message,
                payload=payload or {},
            )
        except Exception:
            logger.debug("记录 task event 失败", exc_info=True)
