from types import SimpleNamespace


def test_routing_service_builds_cpe_request_for_routing_context():
    from agentmind.governance import CPERequest
    from agentmind.services.routing_service import _build_cpe_request_for_routing

    registry = SimpleNamespace(
        executors={
            "local_agent": SimpleNamespace(
                capability=SimpleNamespace(security_level="local")
            ),
            "cloud_agent": SimpleNamespace(
                capability=SimpleNamespace(security_level="cloud")
            ),
        }
    )

    request = _build_cpe_request_for_routing(
        trace_id="t-route",
        user_id="u1",
        agent_id="cloud_agent",
        message="hello",
        agent_registry=registry,
        memories=[{"memory_id": "m1", "access_level": "public"}],
    )

    assert isinstance(request, CPERequest)
    assert request.trace_id == "t-route"
    assert request.user_id == "u1"
    assert request.agent_id == "cloud_agent"
    assert request.agent_security_level == "cloud"
    assert request.context == {"message": "hello", "surface": "routing"}
    assert request.memory_items == [{"memory_id": "m1", "access_level": "public"}]
