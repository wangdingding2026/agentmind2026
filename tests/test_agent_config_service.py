def test_agent_config_service_add_cli_agent_replaces_existing_and_writes():
    from agentmind.services.agent_config_service import AgentConfigService

    writes = []

    class FakeConfigService:
        def read_agents(self):
            return {"agents": [{"id": "a1", "name": "Old", "type": "cli", "tags": []}]}

        def write_agents(self, data):
            writes.append(data)
            return data

    service = AgentConfigService(config_service=FakeConfigService())

    agent = service.add_cli_agent(
        "a1",
        "New",
        "echo ok",
        ["general", "code"],
        health_check="echo ok",
    )

    assert agent == {
        "id": "a1",
        "name": "New",
        "type": "cli",
        "tags": ["general", "code"],
        "enabled": True,
        "timeout": 120,
        "config": {"command": "echo ok", "health_check": "echo ok"},
    }
    assert writes == [{"agents": [agent]}]


def test_agent_config_service_rejects_empty_or_invalid_cli_command():
    from agentmind.services.agent_config_service import AgentConfigService

    class FakeConfigService:
        def read_agents(self):
            raise AssertionError("invalid command should not read config")

        def write_agents(self, data):
            raise AssertionError("invalid command should not write config")

    service = AgentConfigService(config_service=FakeConfigService())

    try:
        service.add_cli_agent("a1", "Agent", "   ", [])
    except ValueError as exc:
        assert "命令不能为空" in str(exc)
    else:
        raise AssertionError("empty command should be rejected")

    try:
        service.add_cli_agent("a1", "Agent", "unterminated 'quote", [])
    except ValueError as exc:
        assert "命令格式无效" in str(exc)
    else:
        raise AssertionError("invalid command should be rejected")


def test_agent_config_service_uses_explicit_health_check():
    from agentmind.services.agent_config_service import AgentConfigService

    writes = []

    class FakeConfigService:
        def read_agents(self):
            return {"agents": []}

        def write_agents(self, data):
            writes.append(data)
            return data

    service = AgentConfigService(config_service=FakeConfigService())

    agent = service.add_cli_agent(
        "a1",
        "Agent",
        "agent-cli run '{instruction}'",
        ["code"],
        health_check="agent-cli doctor",
    )

    assert agent["config"] == {
        "command": "agent-cli run '{instruction}'",
        "health_check": "agent-cli doctor",
    }
    assert writes == [{"agents": [agent]}]


def test_agent_config_service_update_tags_writes_target_agent():
    from agentmind.services.agent_config_service import AgentConfigService

    writes = []

    class FakeConfigService:
        def read_agents(self):
            return {"agents": [{"id": "a1", "name": "Agent", "tags": ["old"]}]}

        def write_agents(self, data):
            writes.append(data)
            return data

    service = AgentConfigService(config_service=FakeConfigService())

    assert service.update_tags("a1", ["new", "code"]) == ["new", "code"]
    assert writes == [{"agents": [{"id": "a1", "name": "Agent", "tags": ["new", "code"]}]}]


def test_agent_config_service_creates_disabled_known_agent_when_updating_missing_tags(monkeypatch):
    from dataclasses import replace

    from agentmind.agents.discovery import KNOWN_AGENTS
    from agentmind.services.agent_config_service import AgentConfigService

    writes = []
    profile = replace(
        KNOWN_AGENTS[0],
        id="known_agent",
        name="Known Agent",
        tags=["old"],
        config={"command": "known '{instruction}'", "health_check": "known --version"},
    )
    monkeypatch.setattr("agentmind.services.agent_config_service.KNOWN_AGENTS", [profile])

    class FakeConfigService:
        def read_agents(self):
            return {"agents": []}

        def write_agents(self, data):
            writes.append(data)
            return data

    service = AgentConfigService(config_service=FakeConfigService())

    assert service.update_or_create_known_agent_tags("known_agent", ["new"]) == ["new"]
    assert writes[0]["agents"][0]["id"] == "known_agent"
    assert writes[0]["agents"][0]["enabled"] is False
    assert writes[0]["agents"][0]["tags"] == ["new"]


def test_agent_config_service_toggle_enabled_writes_target_agent():
    from agentmind.services.agent_config_service import AgentConfigService

    writes = []

    class FakeConfigService:
        def read_agents(self):
            return {"agents": [{"id": "a1", "name": "Agent", "enabled": True}]}

        def write_agents(self, data):
            writes.append(data)
            return data

    service = AgentConfigService(config_service=FakeConfigService())

    assert service.toggle_enabled("a1") is False
    assert writes == [{"agents": [{"id": "a1", "name": "Agent", "enabled": False}]}]


def test_agent_config_service_returns_none_for_missing_agent():
    from agentmind.services.agent_config_service import AgentConfigService

    class FakeConfigService:
        def read_agents(self):
            return {"agents": []}

        def write_agents(self, data):
            raise AssertionError("write_agents should not be called")

    service = AgentConfigService(config_service=FakeConfigService())

    assert service.update_tags("missing", ["x"]) is None
    assert service.toggle_enabled("missing") is None
    assert service.update_or_create_known_agent_tags("missing", ["x"]) is None
