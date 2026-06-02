from agentmind.agents.base import AgentCapability
import pytest
from dataclasses import replace


class _Executor:
    def __init__(self, capability):
        self.capability = capability
        self.is_healthy = True
        self.last_health_check = "2026-05-27T00:00:00Z"
        self.health_checks = 0

    async def health_check(self):
        self.health_checks += 1
        self.is_healthy = False
        return self.is_healthy


class _Registry:
    def __init__(self):
        self.executors = {
            "a1": _Executor(
                AgentCapability(
                    id="a1",
                    name="Agent One",
                    type="api",
                    tags=["code"],
                    enabled=True,
                    timeout=30,
                    description="does work",
                    security_level="cloud",
                    estimated_cost=0.2,
                    avg_latency=3.5,
                    config={"endpoint": "https://example.test", "api_key": "secret"},
                )
            )
        }

    def get_executor(self, agent_id):
        return self.executors.get(agent_id)


class _ConfigService:
    def __init__(self):
        self.masked = []

    def mask_sensitive(self, value):
        self.masked.append(value)
        return {"endpoint": "https://example.test", "api_key": "****"}


class _AgentConfigService:
    def __init__(self):
        self.calls = []

    def update_tags(self, agent_id, tags):
        self.calls.append(("tags", agent_id, tags))
        return tags

    def toggle_enabled(self, agent_id, current_enabled=None):
        self.calls.append(("toggle", agent_id, current_enabled))
        return False

    def build_cli_agent(self, agent_id, name, command, tags, health_check=None):
        self.calls.append(("build", agent_id, name, command, tags, health_check))
        return {
            "id": agent_id,
            "name": name,
            "type": "cli",
            "tags": tags,
            "enabled": True,
            "timeout": 120,
            "config": {"command": command, "health_check": health_check or "echo ok"},
        }

    def add_cli_agent(self, agent_id, name, command, tags, health_check=None):
        self.calls.append(("add", agent_id, name, command, tags, health_check))
        return self.build_cli_agent(agent_id, name, command, tags, health_check)

    def add_agent_config_if_absent(self, agent):
        self.calls.append(("add_config", agent))
        return agent

    def update_or_create_known_agent_tags(self, agent_id, tags):
        self.calls.append(("known_tags", agent_id, tags))
        return tags if agent_id == "known_agent" else None


def test_agent_control_service_lists_agent_management_view_with_masked_config():
    from agentmind.services.agent_control_service import AgentControlService

    config_service = _ConfigService()
    agents = AgentControlService(_Registry(), config_service=config_service).list_agents()

    assert agents == [{
        "id": "a1",
        "name": "Agent One",
        "type": "api",
        "tags": ["code"],
        "enabled": True,
        "timeout": 30,
        "healthy": True,
        "last_health_check": "2026-05-27T00:00:00Z",
        "description": "does work",
        "security_level": "cloud",
        "estimated_cost": 0.2,
        "avg_latency": 3.5,
        "config": {"endpoint": "https://example.test", "api_key": "****"},
    }]
    assert config_service.masked == [{"endpoint": "https://example.test", "api_key": "secret"}]


@pytest.mark.asyncio
async def test_agent_control_service_restarts_existing_agent_and_returns_none_for_missing():
    from agentmind.services.agent_control_service import AgentControlService

    registry = _Registry()
    service = AgentControlService(registry, config_service=_ConfigService())

    restarted = await service.restart_agent("a1")
    missing = await service.restart_agent("missing")

    assert restarted == {"agent_id": "a1", "healthy": False}
    assert registry.get_executor("a1").health_checks == 1
    assert missing is None


def test_agent_control_service_updates_tags_and_runtime_capability():
    from agentmind.services.agent_control_service import AgentControlService

    registry = _Registry()
    agent_config_service = _AgentConfigService()
    service = AgentControlService(
        registry,
        config_service=_ConfigService(),
        agent_config_service=agent_config_service,
    )

    result = service.update_tags("a1", ["new"])
    missing = service.update_tags("missing", ["x"])

    assert result == {"ok": True, "tags": ["new"]}
    assert registry.get_executor("a1").capability.tags == ["new"]
    assert agent_config_service.calls == [
        ("tags", "a1", ["new"]),
        ("known_tags", "missing", ["x"]),
    ]
    assert missing is None


def test_agent_control_service_updates_known_agent_tags_without_runtime_executor():
    from agentmind.services.agent_control_service import AgentControlService

    registry = _Registry()
    agent_config_service = _AgentConfigService()
    service = AgentControlService(
        registry,
        config_service=_ConfigService(),
        agent_config_service=agent_config_service,
    )

    result = service.update_tags("known_agent", ["review"])

    assert result == {"ok": True, "tags": ["review"]}
    assert agent_config_service.calls == [("known_tags", "known_agent", ["review"])]


def test_agent_control_service_toggles_enabled_and_runtime_capability():
    from agentmind.services.agent_control_service import AgentControlService

    registry = _Registry()
    agent_config_service = _AgentConfigService()
    service = AgentControlService(
        registry,
        config_service=_ConfigService(),
        agent_config_service=agent_config_service,
    )

    result = service.toggle_enabled("a1")
    missing = service.toggle_enabled("missing")

    assert result == {"agent_id": "a1", "enabled": False}
    assert registry.get_executor("a1").capability.enabled is False
    assert agent_config_service.calls == [("toggle", "a1", True)]
    assert missing is None


@pytest.mark.asyncio
async def test_agent_control_service_adds_cli_agent_after_successful_health_check():
    from agentmind.agents.cli_executor import CLIExecutor
    from agentmind.services.agent_control_service import AgentControlService

    registry = _Registry()
    agent_config_service = _AgentConfigService()
    service = AgentControlService(
        registry,
        config_service=_ConfigService(),
        agent_config_service=agent_config_service,
    )

    result = await service.add_cli_agent(
        "new_agent",
        "New Agent",
        "echo ok",
        ["general"],
        health_check="echo ok",
    )

    assert result == {"ok": True, "agent_id": "new_agent", "healthy": True}
    assert agent_config_service.calls == [
        ("build", "new_agent", "New Agent", "echo ok", ["general"], "echo ok"),
        ("add", "new_agent", "New Agent", "echo ok", ["general"], "echo ok"),
        ("build", "new_agent", "New Agent", "echo ok", ["general"], "echo ok"),
    ]
    assert isinstance(registry.executors["new_agent"], CLIExecutor)
    assert registry.executors["new_agent"].capability.name == "New Agent"
    assert registry.executors["new_agent"].is_healthy is True


@pytest.mark.asyncio
async def test_agent_control_service_rejects_cli_agent_when_health_check_fails():
    from agentmind.services.agent_control_service import AgentControlService

    registry = _Registry()
    agent_config_service = _AgentConfigService()
    service = AgentControlService(
        registry,
        config_service=_ConfigService(),
        agent_config_service=agent_config_service,
    )

    result = await service.add_cli_agent(
        "bad_agent",
        "Bad Agent",
        "echo ok",
        ["general"],
        health_check="definitely_missing_agentmind_test_command --version",
    )

    assert result["ok"] is False
    assert "健康检查失败" in result["error"]
    assert "bad_agent" not in registry.executors
    assert agent_config_service.calls == [
        (
            "build",
            "bad_agent",
            "Bad Agent",
            "echo ok",
            ["general"],
            "definitely_missing_agentmind_test_command --version",
        )
    ]


@pytest.mark.asyncio
async def test_agent_control_service_rejects_cli_agent_when_command_executable_is_missing():
    from agentmind.services.agent_control_service import AgentControlService

    registry = _Registry()
    agent_config_service = _AgentConfigService()
    service = AgentControlService(
        registry,
        config_service=_ConfigService(),
        agent_config_service=agent_config_service,
    )

    result = await service.add_cli_agent(
        "bad_agent",
        "Bad Agent",
        "definitely_missing_agentmind_test_command '{instruction}'",
        ["general"],
        health_check="echo ok",
    )

    assert result["ok"] is False
    assert "命令不可用" in result["error"]
    assert "bad_agent" not in registry.executors
    assert agent_config_service.calls == [
        (
            "build",
            "bad_agent",
            "Bad Agent",
            "definitely_missing_agentmind_test_command '{instruction}'",
            ["general"],
            "echo ok",
        )
    ]


@pytest.mark.asyncio
async def test_agent_control_service_adds_known_agent_from_simple_open_way(monkeypatch):
    from agentmind.agents.discovery import KNOWN_AGENTS
    from agentmind.services.agent_control_service import AgentControlService

    echo_profile = replace(
        KNOWN_AGENTS[0],
        id="echo_agent",
        name="Echo Agent",
        detect_commands=["echo"],
        tags=["general"],
        config={"command": "echo '{instruction}'", "health_check": "echo ok"},
    )
    monkeypatch.setattr("agentmind.services.agent_control_service.KNOWN_AGENTS", [echo_profile])

    registry = _Registry()
    agent_config_service = _AgentConfigService()
    service = AgentControlService(
        registry,
        config_service=_ConfigService(),
        agent_config_service=agent_config_service,
    )

    result = await service.add_agent_from_open_way(
        agent_name="Echo Agent",
        open_way="echo",
        tags=["general"],
    )

    assert result == {
        "ok": True,
        "agent_id": "echo_agent",
        "healthy": True,
        "message": "已添加 Echo Agent，可以使用了",
    }
    assert agent_config_service.calls[0][0] == "add_config"
    assert registry.executors["echo_agent"].capability.config == {
        "command": "echo '{instruction}'",
        "health_check": "echo ok",
    }


@pytest.mark.asyncio
async def test_agent_control_service_explains_missing_agent_in_plain_language(monkeypatch):
    from agentmind.services.agent_control_service import AgentControlService

    monkeypatch.setattr("agentmind.services.agent_control_service.KNOWN_AGENTS", [])

    registry = _Registry()
    agent_config_service = _AgentConfigService()
    service = AgentControlService(
        registry,
        config_service=_ConfigService(),
        agent_config_service=agent_config_service,
    )

    result = await service.add_agent_from_open_way(
        agent_name="Missing Agent",
        open_way="definitely_missing_agentmind_test_command",
        tags=[],
    )

    assert result == {
        "ok": False,
        "error": "没有找到这个 Agent。请先安装它，或者粘贴它的完整打开方式后再试。",
        "next_step": "安装完成后，回到这里点击“检查并添加”。",
    }
    assert "definitely_missing_agentmind_test_command" not in registry.executors
    assert agent_config_service.calls == []


@pytest.mark.asyncio
async def test_agent_control_service_rejects_already_added_agent(monkeypatch):
    from agentmind.agents.discovery import KNOWN_AGENTS
    from agentmind.services.agent_control_service import AgentControlService

    existing_profile = replace(
        KNOWN_AGENTS[0],
        id="a1",
        name="Agent One",
        detect_commands=["echo"],
        config={"command": "echo '{instruction}'", "health_check": "echo ok"},
    )
    monkeypatch.setattr("agentmind.services.agent_control_service.KNOWN_AGENTS", [existing_profile])

    registry = _Registry()
    agent_config_service = _AgentConfigService()
    service = AgentControlService(
        registry,
        config_service=_ConfigService(),
        agent_config_service=agent_config_service,
    )

    result = await service.add_agent_from_open_way(
        agent_name="Agent One",
        open_way="echo",
        tags=[],
    )

    assert result == {
        "ok": True,
        "agent_id": "a1",
        "healthy": True,
        "message": "Agent One 已经添加过，可以直接使用。",
        "already_added": True,
    }
    assert agent_config_service.calls == []
