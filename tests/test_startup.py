from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agentmind.startup import AgentMindBootstrapper, load_or_generate_token


def test_load_or_generate_token_reuses_existing_token(tmp_path):
    data_home = tmp_path / "agentmind-home"
    token_path = data_home / "config" / "auth.token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text("existing-token-012345678901234567890123", encoding="utf-8")

    token, is_new = load_or_generate_token(data_home)

    assert token == "existing-token-012345678901234567890123"
    assert is_new is False
    assert token_path.read_text(encoding="utf-8") == token


def test_bootstrapper_builds_app_and_keeps_state_local(tmp_path):
    data_home = tmp_path / "agentmind-home"
    config_dir = data_home / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "settings.yaml").write_text("feishu: {enabled: false}\n", encoding="utf-8")
    (config_dir / "agents.yaml").write_text("agents: []\n", encoding="utf-8")
    (config_dir / "routes.yaml").write_text("rules: []\n", encoding="utf-8")

    bootstrapper = AgentMindBootstrapper(port=8765, data_home=data_home)
    app = bootstrapper.create_app()

    assert app.title == "AgentMind"
    assert app.state.auth_token
    assert app.state.agent_registry is not None
    assert app.state.rule_engine is not None
    assert app.state.settings["feishu"]["enabled"] is False


def test_bootstrapper_reports_v1_release_version(tmp_path):
    import tomllib

    data_home = tmp_path / "agentmind-home"
    config_dir = data_home / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "settings.yaml").write_text("feishu: {enabled: false}\n", encoding="utf-8")
    (config_dir / "agents.yaml").write_text("agents: []\n", encoding="utf-8")
    (config_dir / "routes.yaml").write_text("rules: []\n", encoding="utf-8")

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    app = AgentMindBootstrapper(port=8765, data_home=data_home).create_app()

    assert pyproject["project"]["version"] == "1.0.0"
    assert app.version == "1.0.0"


def test_startup_maybe_start_feishu_delegates_to_channel_hub(monkeypatch):
    import asyncio
    import agentmind.startup as startup

    calls = []

    class FakeHub:
        def __init__(self, config_service):
            self.config_service = config_service

        async def maybe_start_feishu(self, app, settings):
            calls.append((self.config_service, app, settings))
            return "adapter"

    app = type("App", (), {"state": object()})()
    config_service = object()
    settings = {"feishu": {"enabled": True, "app_id": "app", "app_secret": "secret"}}
    monkeypatch.setattr(startup, "ChannelHub", FakeHub)

    result = asyncio.run(
        startup._maybe_start_feishu(app, settings, config_service=config_service)
    )

    assert result == "adapter"
    assert calls == [(config_service, app, settings)]


@pytest.mark.asyncio
async def test_startup_restores_session_runtime_state(monkeypatch, tmp_path):
    from agentmind.startup import AgentMindBootstrapper

    calls = []

    class FakeSessionRuntimeService:
        def __init__(self, **kwargs):
            calls.append(("service", kwargs))

        def restore_runtime_state(self):
            calls.append("restore")
            return {"restored_discussions": 1, "restored_attach_bindings": 1}

    async def no_op_health_checks(self):
        calls.append("health")

    monkeypatch.setattr(
        "agentmind.startup.SessionRuntimeService",
        FakeSessionRuntimeService,
        raising=False,
    )
    monkeypatch.setattr(
        "agentmind.agents.registry.AgentRegistry.run_health_checks",
        no_op_health_checks,
    )
    monkeypatch.setattr(
        "agentmind.startup.mark_timed_out_tasks_retriable",
        lambda: calls.append("tasks"),
    )
    monkeypatch.setattr("agentmind.startup._maybe_start_feishu", AsyncMock(return_value=None))

    data_home = tmp_path
    (data_home / "config").mkdir(parents=True)
    (data_home / "config" / "settings.yaml").write_text(
        "feishu:\n  enabled: false\n",
        encoding="utf-8",
    )
    (data_home / "config" / "agents.yaml").write_text("agents: []\n", encoding="utf-8")
    (data_home / "config" / "routes.yaml").write_text("rules: []\n", encoding="utf-8")

    app = AgentMindBootstrapper(port=8765, data_home=data_home).create_app()
    async with app.router.lifespan_context(app):
        pass

    service_call = next(
        call for call in calls
        if isinstance(call, tuple) and call[0] == "service"
    )
    assert service_call[1]["attach_registry"] is app.state.attach_registry
    assert "restore" in calls
