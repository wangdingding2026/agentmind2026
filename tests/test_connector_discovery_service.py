from agentmind.agents.discovery import AgentProfile


def test_connector_discovery_service_lists_connector_templates():
    from agentmind.services.connector_discovery_service import ConnectorDiscoveryService

    profiles = [
        AgentProfile(
            id="demo_cli",
            name="Demo CLI",
            type="cli",
            detect_commands=["demo", "demo --version"],
            tags=["code", "local"],
            timeout=90,
        )
    ]

    result = ConnectorDiscoveryService(profiles=profiles).list_connectors()

    assert result == {
        "connectors": [
            {
                "id": "demo_cli",
                "name": "Demo CLI",
                "type": "cli",
                "tags": ["code", "local"],
                "description": "自动发现：demo, demo --version",
                "timeout": 90,
            }
        ]
    }


def test_connector_discovery_service_uses_known_profiles_by_default():
    from agentmind.services.connector_discovery_service import ConnectorDiscoveryService

    result = ConnectorDiscoveryService().list_connectors()

    assert "connectors" in result
    assert len(result["connectors"]) >= 5
    assert {"id", "name", "type", "tags", "description", "timeout"} <= set(
        result["connectors"][0]
    )
