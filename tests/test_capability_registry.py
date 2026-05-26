from agentmind.agents.base import AgentCapability


class _Executor:
    def __init__(self, capability, *, healthy=True, last_health_check="2026-05-26T00:00:00Z"):
        self.capability = capability
        self.is_healthy = healthy
        self.last_health_check = last_health_check


class _Registry:
    def __init__(self, executors):
        self.executors = executors

    def get_executor(self, agent_id):
        return self.executors.get(agent_id)


def _cap(agent_id, *, protocol="cli", tags=None, cost=0.0, latency=0.0, security="local"):
    return AgentCapability(
        id=agent_id,
        name=f"{agent_id} name",
        type=protocol,
        tags=tags or [],
        enabled=True,
        timeout=5,
        description=f"{agent_id} desc",
        security_level=security,
        estimated_cost=cost,
        avg_latency=latency,
        config={},
    )


def test_capability_registry_lists_profiles_with_runtime_health_and_metrics():
    from agentmind.services.capability_registry import AgentCapabilityRegistry

    registry = _Registry({
        "cheap": _Executor(_cap("cheap", tags=["code"], cost=0.001, latency=1.5)),
        "cloud": _Executor(
            _cap("cloud", protocol="api", security="cloud", cost=0.1, latency=8),
            healthy=False,
        ),
    })
    metrics = {
        "by_agent": {
            "cheap": {"total": 4, "errors": 1, "error_rate": 0.25},
        }
    }

    profiles = AgentCapabilityRegistry(registry, metrics_provider=lambda: metrics).list_profiles()

    assert [p["agent_id"] for p in profiles] == ["cheap", "cloud"]
    assert profiles[0]["protocol"] == "cli"
    assert profiles[0]["tags"] == ["code"]
    assert profiles[0]["healthy"] is True
    assert profiles[0]["success_rate"] == 0.75
    assert profiles[0]["recent_error_count"] == 1
    assert profiles[1]["healthy"] is False
    assert profiles[1]["success_rate"] is None


def test_capability_registry_get_profile_returns_none_for_unknown_agent():
    from agentmind.services.capability_registry import AgentCapabilityRegistry

    registry = _Registry({})

    assert AgentCapabilityRegistry(registry).get_profile("missing") is None
