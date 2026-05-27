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
    assert decision.reason == "no CPE policy matched"
    assert decision.audit_payload["component"] == "CPE"
    assert decision.audit_payload["trace_id"] == "t1"
    assert decision.audit_payload["sensitive_context"] is False


def test_cpe_requires_approval_for_sensitive_context_to_cloud_agent():
    from agentmind.governance import CPE, CPERequest, GovernanceDecisionStatus

    decision = CPE().evaluate(
        CPERequest(
            trace_id="t-sensitive",
            user_id="u1",
            agent_id="cloud_agent",
            agent_security_level="cloud",
            context={"message": "api_key='sk-abc123def456ghi789jkl012mno345pqr678stu'"},
        )
    )

    assert decision.status == GovernanceDecisionStatus.REQUIRE_APPROVAL
    assert decision.risk_level == "high"
    assert decision.reason == "sensitive context requires approval for non-local agent"
    assert decision.audit_payload["sensitive_context"] is True
    assert decision.audit_payload["policy"] == "sensitive-context-non-local-agent"


def test_cpe_allows_sensitive_context_to_local_agent():
    from agentmind.governance import CPE, CPERequest, GovernanceDecisionStatus

    decision = CPE().evaluate(
        CPERequest(
            trace_id="t-local",
            user_id="u1",
            agent_id="local_agent",
            agent_security_level="local",
            context={"message": 'password = "secret"'},
        )
    )

    assert decision.status == GovernanceDecisionStatus.ALLOW
    assert decision.risk_level == "low"
    assert decision.audit_payload["sensitive_context"] is True


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


def test_governance_skeleton_is_not_wired_into_runtime_adapters_or_memory_yet():
    checked_paths = [
        PANEL_SERVER,
        MEMORY_SERVICE,
        *CHANNELS_DIR.glob("*.py"),
    ]
    offenders = []
    for path in checked_paths:
        text = path.read_text(encoding="utf-8")
        if "agentmind.governance" in text:
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []


def test_routing_service_only_has_cpe_request_builder_seam():
    text = ROUTER_SERVICE.read_text(encoding="utf-8")

    assert "agentmind.governance" in text
    assert "def _build_cpe_request_for_routing" in text
    assert "def _record_cpe_routing_dry_run" in text
    assert "record_cpe_decision" in text
    assert "raise HTTPException" not in text
    assert "CPE decision: block" not in text
