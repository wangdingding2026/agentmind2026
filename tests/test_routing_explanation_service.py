import pytest


class _TraceService:
    async def get_trace(self, trace_id):
        if trace_id == "missing":
            return None
        return {
            "trace_id": trace_id,
            "summary": "[explicit] -> a1 (conf=0.85)",
            "agent_id": "a1",
            "strategy": "explicit",
            "confidence": 0.85,
            "fallback_chain": '["a2"]',
            "security_flagged": 0,
            "content": (
                '{"agent_id":"a1","strategy":"explicit","confidence":0.85,'
                '"fallback_chain":["a2"],"raw_message":"hello",'
                '"candidates":["a1","a2"],"security_flagged":false}'
            ),
        }


class _AuditService:
    def __init__(self):
        self.calls = []

    async def query_events(self, **kwargs):
        self.calls.append(kwargs)
        return [
            {"event_id": "e1", "trace_id": "t1", "module": "routing", "action": "decision"},
            {
                "event_id": "e2",
                "trace_id": "t1",
                "module": "governance",
                "action": "cpe_decision",
                "payload": {"decision_status": "allow", "mode": "dry_run"},
            },
        ]


class _CapabilityRegistry:
    def get_profile(self, agent_id):
        return {
            "agent_id": agent_id,
            "name": "Agent One",
            "healthy": True,
            "success_rate": 0.9,
        }


class _StrategyManager:
    def list_strategies(self):
        return [
            {"name": "explicit", "kind": "core", "enabled": True},
            {"name": "signal_scoring", "kind": "core", "enabled": True},
        ]


@pytest.mark.asyncio
async def test_routing_explanation_service_aggregates_trace_context():
    from agentmind.services.routing_explanation_service import RoutingExplanationService

    audit_service = _AuditService()
    service = RoutingExplanationService(
        trace_service=_TraceService(),
        audit_service=audit_service,
        capability_registry=_CapabilityRegistry(),
        strategy_manager=_StrategyManager(),
    )

    explanation = await service.explain("t1")

    assert explanation["trace_id"] == "t1"
    assert explanation["found"] is True
    assert explanation["summary"] == "[explicit] -> a1 (conf=0.85)"
    assert explanation["decision"] == {
        "agent_id": "a1",
        "strategy": "explicit",
        "confidence": 0.85,
        "fallback_chain": ["a2"],
        "security_flagged": False,
        "raw_message": "hello",
        "candidates": ["a1", "a2"],
    }
    assert explanation["selected_agent"]["agent_id"] == "a1"
    assert explanation["selected_agent"]["healthy"] is True
    assert [strategy["name"] for strategy in explanation["strategies"]] == [
        "explicit",
        "signal_scoring",
    ]
    assert explanation["audit_events"] == [
        {"event_id": "e1", "trace_id": "t1", "module": "routing", "action": "decision"},
        {
            "event_id": "e2",
            "trace_id": "t1",
            "module": "governance",
            "action": "cpe_decision",
            "payload": {"decision_status": "allow", "mode": "dry_run"},
        },
    ]
    assert explanation["governance_events"] == [
        {
            "event_id": "e2",
            "trace_id": "t1",
            "module": "governance",
            "action": "cpe_decision",
            "payload": {"decision_status": "allow", "mode": "dry_run"},
        }
    ]
    assert audit_service.calls == [{"trace_id": "t1", "limit": 20}]


@pytest.mark.asyncio
async def test_routing_explanation_service_returns_stable_missing_trace():
    from agentmind.services.routing_explanation_service import RoutingExplanationService

    service = RoutingExplanationService(
        trace_service=_TraceService(),
        audit_service=_AuditService(),
        capability_registry=_CapabilityRegistry(),
        strategy_manager=_StrategyManager(),
    )

    explanation = await service.explain("missing")

    assert explanation == {
        "trace_id": "missing",
        "found": False,
        "summary": "Trace not found",
        "decision": {},
        "selected_agent": None,
        "strategies": [],
        "audit_events": [],
        "governance_events": [],
    }
