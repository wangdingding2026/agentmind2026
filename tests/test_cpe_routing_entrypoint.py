import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.responses import JSONResponse


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


@pytest.mark.asyncio
async def test_routing_service_records_cpe_dry_run_decision(monkeypatch):
    from agentmind.governance import GovernanceDecision, GovernanceDecisionStatus
    from agentmind.services import routing_service

    calls = {}

    class FakeCPE:
        def evaluate(self, request):
            calls["request"] = request
            return GovernanceDecision(
                status=GovernanceDecisionStatus.ALLOW,
                reason="dry-run allow",
                risk_level="low",
                audit_payload={"component": "CPE", "dry_run": True},
            )

    class FakeAuditService:
        async def record_cpe_decision(self, **kwargs):
            calls["audit"] = kwargs

    monkeypatch.setattr(routing_service, "CPE", FakeCPE)
    monkeypatch.setattr(routing_service, "AuditService", FakeAuditService)

    request = routing_service._build_cpe_request_for_routing(
        trace_id="t1",
        user_id="u1",
        agent_id="a1",
        message="hello",
        agent_registry=SimpleNamespace(executors={}),
    )

    await routing_service._record_cpe_routing_dry_run(request)

    assert calls["request"] is request
    assert calls["audit"]["request"] is request
    assert calls["audit"]["decision"].reason == "dry-run allow"
    assert calls["audit"]["actor"] == "system"
    assert calls["audit"]["payload"] == {"surface": "routing", "mode": "dry_run"}


@pytest.mark.asyncio
async def test_route_request_records_cpe_dry_run_without_changing_decision(monkeypatch):
    from agentmind.routing.context import RoutingContext, RoutingDecision
    from agentmind.services import routing_service

    calls = []

    class FakePipeline:
        def __init__(self, agent_registry, engine, strategy_manager=None):
            pass

        async def run(self, msg, identity, settings, is_retry=False):
            return RoutingDecision(
                agent_id="a1",
                strategy="fake",
                confidence=1.0,
                context=RoutingContext(identity=identity, raw_message=msg),
            )

    class FakeExecutor:
        is_healthy = True

    app = SimpleNamespace(
        state=SimpleNamespace(
            agent_registry=SimpleNamespace(
                executors={"a1": FakeExecutor()},
                get_executor=lambda agent_id: FakeExecutor(),
            ),
            rule_engine=object(),
            settings={},
        )
    )

    monkeypatch.setattr(routing_service, "RoutingPipeline", FakePipeline)
    monkeypatch.setattr(routing_service, "record_task_start", AsyncMock())
    monkeypatch.setattr(routing_service, "record_task_update", AsyncMock())
    monkeypatch.setattr(routing_service.TraceRecorder, "record_decision", AsyncMock())
    monkeypatch.setattr(
        routing_service.SingleAgentExecutor,
        "run_json",
        AsyncMock(return_value=JSONResponse(content={"trace_id": "t1", "agent_id": "a1", "result": "ok"})),
    )

    async def fake_dry_run(cpe_request):
        calls.append(cpe_request)

    monkeypatch.setattr(routing_service, "_record_cpe_routing_dry_run", fake_dry_run)

    response = await routing_service._route_request_impl(
        routing_service.RouteRequest(message="hello", stream=False, user_id="u1"),
        app,
    )

    body = json.loads(response.body)
    assert response.status_code == 200
    assert body["agent_id"] == "a1"
    assert len(calls) == 1
    assert calls[0].agent_id == "a1"
    assert calls[0].user_id == "u1"


@pytest.mark.asyncio
async def test_routing_cpe_dry_run_does_not_inspect_customer_message_content(monkeypatch):
    from agentmind.services import routing_service

    calls = {}

    class FakeAuditService:
        async def record_cpe_decision(self, **kwargs):
            calls["audit"] = kwargs

    monkeypatch.setattr(routing_service, "AuditService", FakeAuditService)

    request = routing_service._build_cpe_request_for_routing(
        trace_id="t-sensitive-route",
        user_id="u1",
        agent_id="cloud_agent",
        message="api_key='sk-abc123def456ghi789jkl012mno345pqr678stu'",
        agent_registry=SimpleNamespace(
            executors={
                "cloud_agent": SimpleNamespace(
                    capability=SimpleNamespace(security_level="cloud")
                )
            }
        ),
    )

    await routing_service._record_cpe_routing_dry_run(request)

    decision = calls["audit"]["decision"]
    assert decision.status.value == "allow"
    assert decision.risk_level == "low"
    assert decision.audit_payload["content_inspection"] is False
    assert "sensitive_context" not in decision.audit_payload
    assert calls["audit"]["payload"] == {"surface": "routing", "mode": "dry_run"}
