from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shlex
import shutil
from typing import Any

from agentmind.agents.discovery import AgentProfile, KNOWN_AGENTS, profile_to_agent_config
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

    async def add_agent_from_open_way(
        self,
        agent_name: str,
        open_way: str,
        tags: list[str],
    ) -> dict[str, Any]:
        from agentmind.agents.base import AgentCapability
        from agentmind.agents.cli_executor import CLIExecutor

        open_way = (open_way or "").strip()
        if not open_way:
            return {
                "ok": False,
                "error": "请填写这个 Agent 的打开方式。",
                "next_step": "可以粘贴安装说明里的启动示例，然后点击“检查并添加”。",
            }

        try:
            open_parts = shlex.split(open_way)
        except ValueError:
            return {
                "ok": False,
                "error": "这个打开方式看起来不完整。",
                "next_step": "请直接粘贴安装说明里的启动示例，然后再试。",
            }

        executable = open_parts[0] if open_parts else ""
        profile = self._match_known_profile(agent_name, executable)
        if profile is None:
            if not executable or shutil.which(executable) is None:
                return self._agent_not_found_response()
            return {
                "ok": False,
                "error": "AgentMind 还没有这个 Agent 的添加方式。",
                "next_step": "请选择列表里的 Agent；如果这是新的 Agent，需要先为它增加标准配置。",
            }

        if self._registry.get_executor(profile.id) is not None:
            return {
                "ok": True,
                "agent_id": profile.id,
                "healthy": True,
                "message": f"{profile.name} 已经添加过，可以直接使用。",
                "already_added": True,
            }

        if not executable or shutil.which(executable) is None:
            return self._agent_not_found_response(profile.name)

        candidate_profile = self._profile_with_executable(profile, executable)
        candidate_agent = profile_to_agent_config(candidate_profile)
        if tags:
            candidate_agent["tags"] = tags

        candidate_executor = CLIExecutor(AgentCapability(**candidate_agent))
        if not await candidate_executor.health_check():
            return {
                "ok": False,
                "error": f"找到了 {candidate_profile.name}，但现在还不能正常打开。",
                "next_step": "请先在电脑上打开一次它，完成登录或初始化后，再回到这里点击“检查并添加”。",
            }

        try:
            new_agent = self._agent_config_service.add_agent_config_if_absent(candidate_agent)
        except ValueError:
            return {
                "ok": True,
                "agent_id": candidate_profile.id,
                "healthy": True,
                "message": f"{candidate_profile.name} 已经添加过，可以直接使用。",
                "already_added": True,
            }

        executor = CLIExecutor(AgentCapability(**new_agent))
        executor.is_healthy = True
        executor.last_health_check = candidate_executor.last_health_check
        self._registry.executors[candidate_profile.id] = executor
        return {
            "ok": True,
            "agent_id": candidate_profile.id,
            "healthy": True,
            "message": f"已添加 {candidate_profile.name}，可以使用了",
        }

    async def add_cli_agent(
        self,
        agent_id: str,
        name: str,
        command: str,
        tags: list[str],
        health_check: str | None = None,
    ) -> dict[str, Any]:
        from agentmind.agents.base import AgentCapability
        from agentmind.agents.cli_executor import CLIExecutor

        try:
            candidate_agent = self._agent_config_service.build_cli_agent(
                agent_id,
                name,
                command,
                tags,
                health_check=health_check,
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        command_parts = shlex.split(candidate_agent["config"].get("command", ""))
        executable = command_parts[0] if command_parts else ""
        if not executable or shutil.which(executable) is None:
            return {
                "ok": False,
                "error": f"命令不可用：{executable or command}",
            }

        candidate_executor = CLIExecutor(AgentCapability(**candidate_agent))
        if not await candidate_executor.health_check():
            return {
                "ok": False,
                "error": "健康检查失败，请确认命令和健康检查命令可在当前环境执行",
            }

        new_agent = self._agent_config_service.add_cli_agent(
            agent_id,
            name,
            command,
            tags,
            health_check=health_check,
        )
        cap = AgentCapability(**new_agent)
        executor = CLIExecutor(cap)
        executor.is_healthy = True
        executor.last_health_check = candidate_executor.last_health_check
        self._registry.executors[agent_id] = executor
        return {"ok": True, "agent_id": agent_id, "healthy": True}

    @staticmethod
    def _agent_not_found_response(agent_name: str | None = None) -> dict[str, Any]:
        target = f" {agent_name}" if agent_name else "这个 Agent"
        return {
            "ok": False,
            "error": f"没有找到{target}。请先安装它，或者粘贴它的完整打开方式后再试。",
            "next_step": "安装完成后，回到这里点击“检查并添加”。",
        }

    @staticmethod
    def _match_known_profile(agent_name: str, executable: str) -> AgentProfile | None:
        name_key = (agent_name or "").strip().lower()
        executable_key = Path(executable).name.lower() if executable else ""

        for profile in KNOWN_AGENTS:
            profile_names = {
                profile.id.lower(),
                profile.name.lower(),
                profile.name.lower().replace(" ", ""),
                profile.name.lower().replace(" ", "_"),
            }
            detect_names = {
                Path(shlex.split(command)[0]).name.lower()
                for command in profile.detect_commands
                if command.strip()
            }
            if name_key and name_key in profile_names:
                return profile
            if executable_key and executable_key in detect_names:
                return profile
        return None

    @staticmethod
    def _profile_with_executable(profile: AgentProfile, executable: str) -> AgentProfile:
        config = dict(profile.config)
        for key in ("command", "health_check"):
            value = config.get(key)
            if isinstance(value, str) and value.strip():
                parts = shlex.split(value)
                parts[0] = executable
                config[key] = shlex.join(parts)
        return replace(profile, config=config)

    async def restart_agent(self, agent_id: str) -> dict[str, Any] | None:
        executor = self._registry.get_executor(agent_id)
        if executor is None:
            return None
        await executor.health_check()
        return {"agent_id": agent_id, "healthy": executor.is_healthy}

    def update_tags(self, agent_id: str, tags: list[str]) -> dict[str, Any] | None:
        executor = self._registry.get_executor(agent_id)
        if executor is None:
            saved_tags = self._agent_config_service.update_or_create_known_agent_tags(agent_id, tags)
            if saved_tags is None:
                return None
            return {"ok": True, "tags": saved_tags}
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
