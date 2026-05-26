import tempfile
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI

from agentmind.agents.registry import AgentRegistry
from agentmind.core.rule_engine import RuleEngine
from agentmind.services.routing_service import RoutingService


def build_app(tmp_dir: Path):
    agents_path = tmp_dir / "config" / "agents.yaml"
    routes_path = tmp_dir / "config" / "routes.yaml"
    agents_path.parent.mkdir(parents=True, exist_ok=True)
    agents_path.write_text(
        yaml.dump({
            "agents": [
                {"id": "mock_echo", "name": "Mock Echo", "type": "cli", "tags": ["general"], "enabled": True, "timeout": 5,
                 "config": {"command": "echo done", "health_check": "echo ok"}},
            ]
        }, allow_unicode=True),
        encoding="utf-8",
    )
    routes_path.write_text(yaml.dump({"rules": []}, allow_unicode=True), encoding="utf-8")
    registry = AgentRegistry(agents_path)
    for ex in registry.executors.values():
        ex.is_healthy = True
    engine = RuleEngine(routes_path, agent_registry=registry)
    app = FastAPI()
    app.state.agent_registry = registry
    app.state.rule_engine = engine
    app.state.settings = {"routing": {"use_new_pipeline": True}}
    return app


@pytest.mark.asyncio
async def test_routing_service_route_request_returns_decision(tmp_path):
    app = build_app(tmp_path)
    service = RoutingService(app)

    result = await service.route_request({"message": "写一个函数", "stream": False})

    assert result.agent_id == "mock_echo"
    assert result.trace_id
