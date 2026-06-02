import pytest

import agentmind.agents.discovery as discovery
from agentmind.agents.discovery import (
    AgentProfile,
    KNOWN_AGENTS,
    merge_discovered_agents,
    profiles_to_yaml,
    scan_installed_agents,
)
from agentmind.agents.registry import AgentRegistry


def _auto_profile() -> AgentProfile:
    return AgentProfile(
        id="demo_agent",
        name="Demo Agent",
        type="cli",
        detect_commands=["demo-agent"],
        tags=["auto"],
        timeout=30,
        auto_discovered=True,
        config={
            "command": "demo-agent '{instruction}'",
            "health_check": "demo-agent --version",
        },
    )


def test_auto_discovered_profile_round_trips_through_registry(tmp_path):
    agents_path = tmp_path / "agents.yaml"
    agents_path.write_text(profiles_to_yaml([_auto_profile()]), encoding="utf-8")

    registry = AgentRegistry(agents_path)

    assert list(registry.executors) == ["demo_agent"]
    assert registry.executors["demo_agent"].capability.auto_discovered is True


def test_merge_auto_discovered_profile_round_trips_through_registry(tmp_path):
    agents_path = tmp_path / "agents.yaml"
    agents_path.write_text("agents: []\n", encoding="utf-8")

    merge_discovered_agents(agents_path, [_auto_profile()])
    registry = AgentRegistry(agents_path)

    assert list(registry.executors) == ["demo_agent"]
    assert registry.executors["demo_agent"].capability.auto_discovered is True


@pytest.mark.asyncio
async def test_scan_installed_agents_does_not_probe_unknown_path_executables(
    monkeypatch,
    tmp_path,
):
    executable = tmp_path / "ordinary-tool"
    executable.write_text("", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))

    async def report_not_found(_profile):
        return False, "not_found"

    monkeypatch.setattr("agentmind.agents.discovery._check_command_healthy", report_not_found)
    assert not hasattr(discovery, "_probe_unknown_executable")

    profiles = await scan_installed_agents()

    assert profiles == []


def test_known_agent_ids_are_only_agent_tools():
    assert {profile.id for profile in KNOWN_AGENTS} == {
        "claude_code",
        "hermes",
        "codex",
        "aider",
        "cursor_agent",
        "warp_agent",
        "openclaw",
    }
