from agentmind.agents.base import AgentCapability


class _Executor:
    def __init__(self, capability):
        self.capability = capability
        self.is_healthy = True
        self.last_health_check = "2026-05-27T00:00:00Z"


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


class _ConfigService:
    def __init__(self):
        self.masked = []

    def mask_sensitive(self, value):
        self.masked.append(value)
        return {"endpoint": "https://example.test", "api_key": "****"}


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
