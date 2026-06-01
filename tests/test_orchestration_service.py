import pytest


@pytest.mark.asyncio
async def test_route_request_orchestration_stream_yields_engine_events(tmp_path, monkeypatch):
    import json

    from agentmind.agents.registry import AgentRegistry
    from agentmind.core.rule_engine import RuleEngine
    from agentmind.services import routing_service
    from agentmind.services.routing_service import RoutingService
    from fastapi import FastAPI

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    agents_path = config_dir / "agents.yaml"
    routes_path = config_dir / "routes.yaml"
    agents_path.write_text("agents: []\n", encoding="utf-8")
    routes_path.write_text("rules: []\n", encoding="utf-8")

    app = FastAPI()
    app.state.agent_registry = AgentRegistry(agents_path)
    app.state.rule_engine = RuleEngine(routes_path, agent_registry=app.state.agent_registry)
    app.state.settings = {}

    class FakeOrchestrationService:
        def match_plan(self, message):
            return {
                "plan_id": "flow-1",
                "steps": [{"step_id": 1, "agent_id": "a", "instruction": "run", "depends_on": []}],
            }

    class FakeEngine:
        async def execute_events(self, plan, agent_registry, initial_instruction=""):
            yield {"event": "node_status", "data": {"step_id": 1, "status": "executing"}}
            yield {"event": "partial", "data": {"step_id": 1, "content": "hello"}}
            yield {"event": "status", "data": {"status": "orchestration_complete", "plan_id": plan.plan_id}}

    monkeypatch.setattr(routing_service, "OrchestrationService", FakeOrchestrationService)
    monkeypatch.setattr(routing_service, "OrchestrationEngine", lambda: FakeEngine())

    listener = routing_service.register_stream_listener("flow-1")
    try:
        response = await RoutingService(app).route_request({
            "message": "run flow",
            "user_id": "u1",
            "stream": True,
        })

        chunks = [chunk async for chunk in response.body_iterator]
        panel_chunks = [listener.get_nowait() for _ in chunks]
    finally:
        routing_service.unregister_stream_listener("flow-1", listener)

    assert chunks == [
        {"event": "node_status", "data": json.dumps({"step_id": 1, "status": "executing"})},
        {"event": "partial", "data": json.dumps({"step_id": 1, "content": "hello"})},
        {"event": "status", "data": json.dumps({"status": "orchestration_complete", "plan_id": "flow-1"})},
    ]
    assert panel_chunks == chunks


def test_orchestration_service_saves_lists_and_preserves_usage_count(tmp_path):
    from agentmind.services.orchestration_service import OrchestrationService

    service = OrchestrationService(tmp_path)
    service.save_plan("daily", "Daily Review", ["review"], [{"step_id": 1}])
    service.increment_usage("daily")
    service.save_plan("daily", "Daily Review v2", ["复盘"], [{"step_id": 2}])

    plans = service.list_plans()

    assert plans == [
        {
            "plan_id": "daily",
            "name": "Daily Review v2",
            "trigger_words": ["复盘"],
            "steps": [{"step_id": 2}],
            "usage_count": 1,
        }
    ]


def test_orchestration_service_deletes_plan(tmp_path):
    from agentmind.services.orchestration_service import OrchestrationService

    service = OrchestrationService(tmp_path)
    service.save_plan("keep", "Keep", [], [])
    service.save_plan("drop", "Drop", [], [])

    assert service.delete_plan("drop") == {"ok": True}

    assert [plan["plan_id"] for plan in service.list_plans()] == ["keep"]


def test_orchestration_service_matches_trigger_case_insensitive_and_increments_usage(tmp_path):
    from agentmind.services.orchestration_service import OrchestrationService

    service = OrchestrationService(tmp_path)
    service.save_plan("research", "Research", ["Deep Research"], [])

    matched = service.match_plan("please run deep research now")

    assert matched["plan_id"] == "research"
    assert service.list_plans()[0]["usage_count"] == 1


def test_orchestration_service_returns_none_when_no_trigger_matches(tmp_path):
    from agentmind.services.orchestration_service import OrchestrationService

    service = OrchestrationService(tmp_path)
    service.save_plan("research", "Research", ["research"], [])

    assert service.match_plan("ordinary message") is None


def test_api_orchestration_legacy_storage_helpers_delegate_to_service(monkeypatch):
    import agentmind.api.orchestration as api_orchestration

    calls = []

    class FakeService:
        def list_plans(self):
            calls.append(("list",))
            return [{"plan_id": "p1"}]

        def replace_plans(self, plans):
            calls.append(("replace", plans))

        def increment_usage(self, plan_id):
            calls.append(("increment", plan_id))

    monkeypatch.setattr(api_orchestration, "_orchestration_service", lambda: FakeService(), raising=False)

    assert api_orchestration._load_orchestrations() == [{"plan_id": "p1"}]
    api_orchestration._save_orchestrations([{"plan_id": "p2"}])
    api_orchestration._increment_orchestration_usage("p2")

    assert calls == [
        ("list",),
        ("replace", [{"plan_id": "p2"}]),
        ("increment", "p2"),
    ]


def test_routing_service_match_orchestration_delegates_to_orchestration_service(monkeypatch):
    from agentmind.services import routing_service

    calls = []

    class FakeService:
        def match_plan(self, message):
            calls.append(message)
            return {"plan_id": "matched"}

    monkeypatch.setattr(routing_service, "OrchestrationService", lambda: FakeService(), raising=False)

    assert routing_service._match_orchestration("run the flow") == {"plan_id": "matched"}
    assert calls == ["run the flow"]


@pytest.mark.asyncio
async def test_routing_service_execute_orchestration_plan_uses_engine_events(monkeypatch):
    from agentmind.services import routing_service

    sent = []
    calls = []

    class FakeEngine:
        async def execute_events(self, plan, agent_registry, initial_instruction=""):
            calls.append((plan.plan_id, agent_registry, initial_instruction))
            yield {"event": "partial", "data": {"step_id": 1, "content": "hello"}}
            yield {
                "event": "node_status",
                "data": {"step_id": 2, "status": "failed", "error": "no agent"},
            }

    async def send_func(message):
        sent.append(message)

    registry = object()
    monkeypatch.setattr(routing_service, "OrchestrationEngine", lambda: FakeEngine(), raising=False)

    chunks = [
        chunk async for chunk in routing_service._execute_orchestration_plan(
            {
                "plan_id": "p1",
                "steps": [{"step_id": 1, "agent_id": "a", "instruction": "run", "depends_on": []}],
            },
            "u1",
            registry,
            send_func,
            "user message",
        )
    ]

    assert calls == [("p1", registry, "user message")]
    assert sent == ["hello", "编排步骤 2 失败：no agent"]
    assert [chunk["event"] for chunk in chunks] == ["partial", "node_status"]


@pytest.mark.asyncio
async def test_route_stream_orchestration_consumes_event_generator(monkeypatch):
    from agentmind.services import routing_service

    calls = []

    class FakeEngine:
        async def execute_events(self, plan, agent_registry, initial_instruction=""):
            calls.append((plan.plan_id, agent_registry, initial_instruction))
            yield {"event": "partial", "data": {"step_id": 1, "content": "hello"}}
            yield {"event": "status", "data": {"status": "orchestration_complete", "plan_id": plan.plan_id}}

    monkeypatch.setattr(routing_service, "OrchestrationEngine", lambda: FakeEngine(), raising=False)
    monkeypatch.setattr(
        routing_service,
        "_match_orchestration",
        lambda msg: {
            "plan_id": "flow-text",
            "steps": [{"step_id": 1, "agent_id": "a", "instruction": "run", "depends_on": []}],
        },
    )

    registry = object()
    chunks = [
        chunk async for chunk in routing_service.route_stream(
            "run flow",
            "u1",
            registry,
            object(),
            {},
        )
    ]

    assert calls == [("flow-text", registry, "run flow")]
    assert chunks == ["【AgentMind】\n编排执行完成"]
