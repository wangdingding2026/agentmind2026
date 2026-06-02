from __future__ import annotations

from copy import deepcopy
import shlex
from pathlib import Path
from typing import Any

from agentmind.agents.discovery import KNOWN_AGENTS, profile_to_agent_config
from agentmind.services.config_service import ConfigService


class AgentConfigService:
    """Agent-specific configuration mutations backed by ConfigService."""

    def __init__(self, config_dir: Path | None = None, config_service: ConfigService | None = None):
        self.config_service = config_service or ConfigService(config_dir)

    def build_cli_agent(
        self,
        agent_id: str,
        name: str,
        command: str,
        tags: list[str],
        health_check: str | None = None,
    ) -> dict[str, Any]:
        command_parts = self._parse_command(command, field_name="命令")
        health_check = (health_check or f"{command_parts[0]} --version").strip()
        self._parse_command(health_check, field_name="健康检查命令")
        new_agent = {
            "id": agent_id,
            "name": name,
            "type": "cli",
            "tags": tags,
            "enabled": True,
            "timeout": 120,
            "config": {
                "command": command,
                "health_check": health_check,
            },
        }
        return new_agent

    def add_cli_agent(
        self,
        agent_id: str,
        name: str,
        command: str,
        tags: list[str],
        health_check: str | None = None,
    ) -> dict[str, Any]:
        new_agent = self.build_cli_agent(
            agent_id,
            name,
            command,
            tags,
            health_check=health_check,
        )
        data = self.config_service.read_agents()
        agents = [agent for agent in data.get("agents", []) if isinstance(agent, dict) and agent.get("id") != agent_id]
        agents.append(new_agent)
        data["agents"] = agents
        self.config_service.write_agents(data)
        return new_agent

    def add_agent_config_if_absent(self, agent: dict[str, Any]) -> dict[str, Any]:
        agent_id = agent.get("id")
        if not agent_id:
            raise ValueError("Agent ID 不能为空")

        data = self.config_service.read_agents()
        agents = [item for item in data.get("agents", []) if isinstance(item, dict)]
        if any(item.get("id") == agent_id for item in agents):
            raise ValueError("这个 Agent 已经添加过")

        saved_agent = deepcopy(agent)
        agents.append(saved_agent)
        data["agents"] = agents
        self.config_service.write_agents(data)
        return saved_agent

    @staticmethod
    def _parse_command(command: str, *, field_name: str) -> list[str]:
        if not command or not command.strip():
            raise ValueError(f"{field_name}不能为空")
        try:
            parts = shlex.split(command)
        except ValueError as exc:
            raise ValueError(f"{field_name}格式无效: {exc}") from exc
        if not parts:
            raise ValueError(f"{field_name}不能为空")
        return parts

    def update_tags(self, agent_id: str, tags: list[str]) -> list[str] | None:
        data = self.config_service.read_agents()
        agents = data.get("agents", [])
        for agent in agents:
            if isinstance(agent, dict) and agent.get("id") == agent_id:
                agent["tags"] = tags
                self.config_service.write_agents(data)
                return tags
        return None

    def update_or_create_known_agent_tags(self, agent_id: str, tags: list[str]) -> list[str] | None:
        data = self.config_service.read_agents()
        agents = [agent for agent in data.get("agents", []) if isinstance(agent, dict)]
        for agent in agents:
            if agent.get("id") == agent_id:
                agent["tags"] = tags
                data["agents"] = agents
                self.config_service.write_agents(data)
                return tags

        profile = next((profile for profile in KNOWN_AGENTS if profile.id == agent_id), None)
        if profile is None:
            return None

        agent = profile_to_agent_config(profile)
        agent["enabled"] = False
        agent["tags"] = tags
        agents.append(agent)
        data["agents"] = agents
        self.config_service.write_agents(data)
        return tags

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
