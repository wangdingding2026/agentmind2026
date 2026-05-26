from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agentmind.storage.db import _get_metrics_sync


class AgentCapabilityRegistry:
    def __init__(self, agent_registry, metrics_provider: Callable[[], dict] | None = None):
        self._registry = agent_registry
        self._metrics_provider = metrics_provider or _get_metrics_sync

    def list_profiles(self) -> list[dict[str, Any]]:
        return [
            self._profile_for(agent_id, executor, self._agent_metrics(agent_id))
            for agent_id, executor in self._registry.executors.items()
        ]

    def get_profile(self, agent_id: str) -> dict[str, Any] | None:
        executor = self._registry.get_executor(agent_id)
        if executor is None:
            return None
        return self._profile_for(agent_id, executor, self._agent_metrics(agent_id))

    def score_inputs(self, agent_id: str) -> dict[str, Any] | None:
        profile = self.get_profile(agent_id)
        if profile is None:
            return None
        return {
            "estimated_cost": profile["estimated_cost"],
            "avg_latency": profile["avg_latency"],
            "security_level": profile["security_level"],
            "success_rate": profile["success_rate"],
        }

    def record_health(self, agent_id: str, healthy: bool) -> dict[str, Any] | None:
        executor = self._registry.get_executor(agent_id)
        if executor is None:
            return None
        executor.is_healthy = bool(healthy)
        return self.get_profile(agent_id)

    def _agent_metrics(self, agent_id: str) -> dict[str, Any]:
        try:
            metrics = self._metrics_provider() or {}
        except Exception:
            metrics = {}
        by_agent = metrics.get("by_agent", {}) if isinstance(metrics, dict) else {}
        agent_metrics = by_agent.get(agent_id, {}) if isinstance(by_agent, dict) else {}
        return agent_metrics if isinstance(agent_metrics, dict) else {}

    def _profile_for(self, agent_id: str, executor, metrics: dict[str, Any]) -> dict[str, Any]:
        cap = executor.capability
        total = metrics.get("total")
        errors = metrics.get("errors")
        success_rate = None
        if isinstance(total, int | float) and total > 0:
            error_count = int(errors or 0)
            success_rate = round(max(0.0, 1.0 - (error_count / total)), 3)
        return {
            "agent_id": agent_id,
            "name": cap.name,
            "protocol": cap.type,
            "tags": list(cap.tags or []),
            "description": cap.description,
            "security_level": cap.security_level,
            "estimated_cost": cap.estimated_cost,
            "avg_latency": cap.avg_latency,
            "healthy": bool(executor.is_healthy),
            "last_health_check": executor.last_health_check,
            "success_rate": success_rate,
            "recent_error_count": int(errors or 0),
        }
