from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOVERNANCE_DIR = PROJECT_ROOT / "src" / "agentmind" / "governance"
PANEL_SERVER = PROJECT_ROOT / "src" / "agentmind" / "panel" / "server.py"
CHANNELS_DIR = PROJECT_ROOT / "src" / "agentmind" / "channels"
ROUTER_SERVICE = PROJECT_ROOT / "src" / "agentmind" / "services" / "routing_service.py"
MEMORY_SERVICE = PROJECT_ROOT / "src" / "agentmind" / "memory" / "service.py"


def test_governance_package_files_exist():
    expected = {
        "__init__.py",
        "types.py",
        "cpe.py",
        "agent_shield.py",
    }
    missing = sorted(name for name in expected if not (GOVERNANCE_DIR / name).exists())

    assert missing == []


def test_cpe_default_decision_contract_allows_without_runtime_policy():
    from agentmind.governance import (
        CPE,
        CPERequest,
        GovernanceDecision,
        GovernanceDecisionStatus,
    )

    decision = CPE().evaluate(
        CPERequest(
            trace_id="t1",
            user_id="u1",
            agent_id="a1",
            agent_security_level="local",
            context={"message": "hello"},
            memory_items=[{"memory_id": "m1", "access_level": "public"}],
        )
    )

    assert isinstance(decision, GovernanceDecision)
    assert decision.status == GovernanceDecisionStatus.ALLOW
    assert decision.risk_level == "low"
    assert decision.reason == "no governance policy configured"
    assert decision.audit_payload["component"] == "CPE"
    assert decision.audit_payload["trace_id"] == "t1"


def test_agent_shield_default_decision_contract_allows_without_runtime_policy():
    from agentmind.governance import (
        AgentShield,
        AgentShieldRequest,
        GovernanceDecision,
        GovernanceDecisionStatus,
    )

    decision = AgentShield().evaluate(
        AgentShieldRequest(
            trace_id="t2",
            user_id="u1",
            agent_id="a1",
            action="execute",
            target="local-agent",
            payload={"instruction": "summarize"},
        )
    )

    assert isinstance(decision, GovernanceDecision)
    assert decision.status == GovernanceDecisionStatus.ALLOW
    assert decision.risk_level == "low"
    assert decision.reason == "no governance policy configured"
    assert decision.audit_payload["component"] == "AgentShield"
    assert decision.audit_payload["action"] == "execute"


def test_governance_skeleton_is_not_wired_into_runtime_adapters_or_services_yet():
    checked_paths = [
        PANEL_SERVER,
        ROUTER_SERVICE,
        MEMORY_SERVICE,
        *CHANNELS_DIR.glob("*.py"),
    ]
    offenders = []
    for path in checked_paths:
        text = path.read_text(encoding="utf-8")
        if "agentmind.governance" in text:
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []
