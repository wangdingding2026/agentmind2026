from __future__ import annotations

from pathlib import Path
from typing import Any

from agentmind.services.agent_config_service import AgentConfigService
from agentmind.services.config_service import ConfigService


class AgentControlService:
    """Build Agent management views for control-plane clients."""

    def __init__(
        self,
        agent_registry,
        config_service: ConfigService | None = None,
        agent_config_service: AgentConfigService | None = None,
        config_dir: Path | None = None,
    ):
        self._registry = agent_registry
        self._config_service = config_service or ConfigService(config_dir)
        self._agent_config_service = agent_config_service or AgentConfigService(
            config_service=self._config_service
        )

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

    async def restart_agent(self, agent_id: str) -> dict[str, Any] | None:
        executor = self._registry.get_executor(agent_id)
        if executor is None:
            return None
        await executor.health_check()
        return {"agent_id": agent_id, "healthy": executor.is_healthy}

    def update_tags(self, agent_id: str, tags: list[str]) -> dict[str, Any] | None:
        executor = self._registry.get_executor(agent_id)
        if executor is None:
            return None
        saved_tags = self._agent_config_service.update_tags(agent_id, tags)
        if saved_tags is None:
            return None
        executor.capability.tags = saved_tags
        return {"ok": True, "tags": saved_tags}

    def toggle_enabled(self, agent_id: str) -> dict[str, Any] | None:
        executor = self._registry.get_executor(agent_id)
        if executor is None:
            return None
        new_enabled = self._agent_config_service.toggle_enabled(
            agent_id,
            executor.capability.enabled,
        )
        if new_enabled is None:
            return None
        executor.capability.enabled = new_enabled
        return {"agent_id": agent_id, "enabled": new_enabled}
