from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from agentmind.services.config_service import ConfigService


class AgentConfigService:
    """Agent-specific configuration mutations backed by ConfigService."""

    def __init__(self, config_dir: Path | None = None, config_service: ConfigService | None = None):
        self.config_service = config_service or ConfigService(config_dir)

    def add_cli_agent(self, agent_id: str, name: str, command: str, tags: list[str]) -> dict[str, Any]:
        new_agent = {
            "id": agent_id,
            "name": name,
            "type": "cli",
            "tags": tags,
            "enabled": True,
            "timeout": 120,
            "config": {
                "command": command,
                "health_check": f"{shlex.split(command)[0]} --version",
            },
        }
        data = self.config_service.read_agents()
        agents = [agent for agent in data.get("agents", []) if isinstance(agent, dict) and agent.get("id") != agent_id]
        agents.append(new_agent)
        data["agents"] = agents
        self.config_service.write_agents(data)
        return new_agent

    def update_tags(self, agent_id: str, tags: list[str]) -> list[str] | None:
        data = self.config_service.read_agents()
        agents = data.get("agents", [])
        for agent in agents:
            if isinstance(agent, dict) and agent.get("id") == agent_id:
                agent["tags"] = tags
                self.config_service.write_agents(data)
                return tags
        return None

    def toggle_enabled(self, agent_id: str, current_enabled: bool | None = None) -> bool | None:
        data = self.config_service.read_agents()
        agents = data.get("agents", [])
        for agent in agents:
            if isinstance(agent, dict) and agent.get("id") == agent_id:
                new_enabled = not (agent.get("enabled", True) if current_enabled is None else current_enabled)
                agent["enabled"] = new_enabled
                self.config_service.write_agents(data)
                return new_enabled
        return None
