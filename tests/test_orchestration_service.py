import pytest


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

    await routing_service._execute_orchestration_plan(
        {
            "plan_id": "p1",
            "steps": [{"step_id": 1, "agent_id": "a", "instruction": "run", "depends_on": []}],
        },
        "u1",
        registry,
        send_func,
        "user message",
    )

    assert calls == [("p1", registry, "user message")]
    assert sent == ["hello", "编排步骤 2 失败：no agent"]
