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

    agent = service.add_cli_agent("a1", "New", "echo ok", ["general", "code"])

    assert agent == {
        "id": "a1",
        "name": "New",
        "type": "cli",
        "tags": ["general", "code"],
        "enabled": True,
        "timeout": 120,
        "config": {"command": "echo ok", "health_check": "echo --version"},
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
