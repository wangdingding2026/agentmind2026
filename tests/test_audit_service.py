import json
import sqlite3

import pytest


@pytest.mark.asyncio
async def test_audit_service_records_and_queries_events(tmp_path):
    from agentmind.services.audit_service import AuditService

    service = AuditService(str(tmp_path / "trace.db"))

    event_id = await service.record_event(
        module="routing",
        action="decision",
        actor="system",
        user_id="u1",
        trace_id="t1",
        agent_id="a1",
        risk_level="low",
        status="success",
        message="routed to a1",
        payload={"strategy": "explicit", "confidence": 0.9},
    )

    events = await service.query_events()

    assert len(events) == 1
    assert events[0]["event_id"] == event_id
    assert events[0]["module"] == "routing"
    assert events[0]["action"] == "decision"
    assert events[0]["actor"] == "system"
    assert events[0]["user_id"] == "u1"
    assert events[0]["trace_id"] == "t1"
    assert events[0]["agent_id"] == "a1"
    assert events[0]["risk_level"] == "low"
    assert events[0]["status"] == "success"
    assert events[0]["message"] == "routed to a1"
    assert events[0]["payload"] == {"strategy": "explicit", "confidence": 0.9}


@pytest.mark.asyncio
async def test_audit_service_query_filters_and_orders_newest_first(tmp_path):
    from agentmind.services.audit_service import AuditService

    service = AuditService(str(tmp_path / "trace.db"))
    await service.record_event(module="config", action="update", actor="admin", risk_level="medium")
    await service.record_event(module="routing", action="decision", actor="system", trace_id="t1", agent_id="a1", risk_level="low")
    await service.record_event(module="routing", action="blocked", actor="system", trace_id="t2", agent_id="a2", risk_level="high")

    routing_events = await service.query_events(module="routing")
    high_events = await service.query_events(risk_level="high")
    agent_events = await service.query_events(agent_id="a1")
    trace_events = await service.query_events(trace_id="t2")
    actor_events = await service.query_events(actor="admin")

    assert [event["action"] for event in routing_events] == ["blocked", "decision"]
    assert [event["trace_id"] for event in high_events] == ["t2"]
    assert [event["trace_id"] for event in agent_events] == ["t1"]
    assert [event["agent_id"] for event in trace_events] == ["a2"]
    assert [event["module"] for event in actor_events] == ["config"]


@pytest.mark.asyncio
async def test_audit_service_query_filters_by_action_and_limit(tmp_path):
    from agentmind.services.audit_service import AuditService

    service = AuditService(str(tmp_path / "trace.db"))
    await service.record_event(module="config", action="create", message="first")
    await service.record_event(module="config", action="update", message="second")
    await service.record_event(module="config", action="update", message="third")

    events = await service.query_events(module="config", action="update", limit=1)

    assert len(events) == 1
    assert events[0]["action"] == "update"
    assert events[0]["message"] == "third"


@pytest.mark.asyncio
async def test_audit_service_record_routing_decision_helper(tmp_path):
    from agentmind.services.audit_service import AuditService

    service = AuditService(str(tmp_path / "trace.db"))

    await service.record_routing_decision(
        trace_id="t1",
        agent_id="a1",
        strategy="explicit",
        confidence=0.75,
        actor="system",
        user_id="u1",
        risk_level="low",
        payload={"candidates": ["a1", "a2"]},
    )

    events = await service.query_events(module="routing", action="decision")

    assert len(events) == 1
    assert events[0]["trace_id"] == "t1"
    assert events[0]["agent_id"] == "a1"
    assert events[0]["message"] == "routing decision: explicit -> a1"
    assert events[0]["payload"] == {
        "strategy": "explicit",
        "confidence": 0.75,
        "candidates": ["a1", "a2"],
    }


def test_audit_events_are_persisted_as_json_payload(tmp_path):
    from agentmind.services.audit_service import AuditService

    service = AuditService(str(tmp_path / "trace.db"))
    event_id = service._record_event_sync(
        module="memory",
        action="read",
        payload={"memory_id": "m1"},
    )

    conn = sqlite3.connect(str(tmp_path / "trace.db"))
    try:
        row = conn.execute("SELECT payload FROM audit_events WHERE event_id=?", (event_id,)).fetchone()
    finally:
        conn.close()

    assert json.loads(row[0]) == {"memory_id": "m1"}


@pytest.mark.asyncio
async def test_audit_service_record_cpe_decision_helper(tmp_path):
    from agentmind.governance import CPERequest, GovernanceDecision, GovernanceDecisionStatus
    from agentmind.services.audit_service import AuditService

    service = AuditService(str(tmp_path / "trace.db"))
    request = CPERequest(
        trace_id="t-cpe",
        user_id="u1",
        agent_id="cloud-agent",
        agent_security_level="cloud",
        memory_items=[{"memory_id": "m1"}, {"memory_id": "m2"}],
    )
    decision = GovernanceDecision(
        status=GovernanceDecisionStatus.REQUIRE_APPROVAL,
        reason="sensitive context requires approval",
        risk_level="high",
        audit_payload={"component": "CPE", "sensitive": True},
    )

    await service.record_cpe_decision(
        request=request,
        decision=decision,
        actor="system",
        payload={"policy": "sensitive-context"},
    )

    events = await service.query_events(module="governance", action="cpe_decision")

    assert len(events) == 1
    assert events[0]["trace_id"] == "t-cpe"
    assert events[0]["user_id"] == "u1"
    assert events[0]["agent_id"] == "cloud-agent"
    assert events[0]["risk_level"] == "high"
    assert events[0]["status"] == "approval_required"
    assert events[0]["message"] == "CPE decision: require_approval"
    assert events[0]["payload"] == {
        "component": "CPE",
        "decision_status": "require_approval",
        "reason": "sensitive context requires approval",
        "agent_security_level": "cloud",
        "memory_count": 2,
        "sensitive": True,
        "policy": "sensitive-context",
    }
