from agentmind.agents.base import AgentCapability
import pytest


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

    def add_cli_agent(self, agent_id, name, command, tags):
        self.calls.append(("add", agent_id, name, command, tags))
        return {
            "id": agent_id,
            "name": name,
            "type": "cli",
            "tags": tags,
            "enabled": True,
            "timeout": 120,
            "config": {"command": command, "health_check": "echo --version"},
        }


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
    assert agent_config_service.calls == [("tags", "a1", ["new"])]
    assert missing is None


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


def test_agent_control_service_adds_cli_agent_and_registers_runtime_executor():
    from agentmind.agents.cli_executor import CLIExecutor
    from agentmind.services.agent_control_service import AgentControlService

    registry = _Registry()
    agent_config_service = _AgentConfigService()
    service = AgentControlService(
        registry,
        config_service=_ConfigService(),
        agent_config_service=agent_config_service,
    )

    result = service.add_cli_agent("new_agent", "New Agent", "echo ok", ["general"])

    assert result == {"ok": True}
    assert agent_config_service.calls == [
        ("add", "new_agent", "New Agent", "echo ok", ["general"])
    ]
    assert isinstance(registry.executors["new_agent"], CLIExecutor)
    assert registry.executors["new_agent"].capability.name == "New Agent"
