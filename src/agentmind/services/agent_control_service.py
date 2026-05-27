from __future__ import annotations

from pathlib import Path
from typing import Any

from agentmind.services.config_service import ConfigService


class AgentControlService:
    """Build Agent management views for control-plane clients."""

    def __init__(
        self,
        agent_registry,
        config_service: ConfigService | None = None,
        config_dir: Path | None = None,
    ):
        self._registry = agent_registry
        self._config_service = config_service or ConfigService(config_dir)

    def list_agents(self) -> list[dict[str, Any]]:
        agents = []
        for agent_id, executor in self._registry.executors.items():
            cap = executor.capability
            agents.append({
                "id": agent_id,
                "name": cap.name,
                "type": cap.type,
                "tags": cap.tags,
                "enabled": cap.enabled,
                "timeout": cap.timeout,
                "healthy": executor.is_healthy,
                "last_health_check": executor.last_health_check,
                "description": cap.description,
                "security_level": cap.security_level,
                "estimated_cost": cap.estimated_cost,
                "avg_latency": cap.avg_latency,
                "config": self._config_service.mask_sensitive(cap.config),
            })
        return agents
