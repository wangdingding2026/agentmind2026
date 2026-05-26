import json
import sqlite3

import pytest

from agentmind.routing.context import RequestIdentity, RoutingContext, RoutingDecision


def _decision() -> RoutingDecision:
    return RoutingDecision(
        agent_id="a1",
        strategy="explicit",
        confidence=0.85,
        fallback_chain=["a2"],
        reply_text="ok",
        context=RoutingContext(
            identity=RequestIdentity(trace_id="t1", user_id="u1"),
            raw_message="hello",
            candidates=["a1", "a2"],
            security_flagged=False,
        ),
    )


@pytest.mark.asyncio
async def test_trace_service_records_decision_outside_memory_db():
    from agentmind.services.trace_service import TraceService
    from agentmind.storage.db import DATA_DIR

    svc = TraceService()
    await svc.record_decision("t1", _decision(), user_id="u1")

    trace = await svc.get_trace("t1")

    assert trace is not None
    assert trace["trace_id"] == "t1"
    assert trace["agent_id"] == "a1"
    assert trace["strategy"] == "explicit"
    assert trace["summary"] == "[explicit] -> a1 (conf=0.85)"
    content = json.loads(trace["content"])
    assert content["raw_message"] == "hello"

    conn = sqlite3.connect(str(DATA_DIR / "memory.db"))
    try:
        row = conn.execute(
            "SELECT memory_id FROM memory_entries WHERE memory_id=?",
            ("trace-t1",),
        ).fetchone()
    finally:
        conn.close()
    assert row is None


@pytest.mark.asyncio
async def test_trace_service_reads_legacy_memory_trace():
    from agentmind.services.trace_service import TraceService
    from agentmind.storage.db import DATA_DIR

    conn = sqlite3.connect(str(DATA_DIR / "memory.db"))
    try:
        conn.execute(
            """INSERT INTO memory_entries
               (memory_id, content, summary, source_agent, source_task_id, created_at, access_level, tags, user_id)
               VALUES (?, ?, ?, ?, ?, datetime('now'), ?, ?, ?)""",
            (
                "trace-old",
                '{"agent_id": "legacy"}',
                "[legacy] -> old (conf=0.4)",
                "agentmind",
                "old",
                "private",
                '["routing_trace"]',
                "u1",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    trace = await TraceService().get_trace("old")

    assert trace is not None
    assert trace["summary"] == "[legacy] -> old (conf=0.4)"
    assert trace["memory_id"] == "trace-old"


@pytest.mark.asyncio
async def test_trace_recorder_delegates_to_trace_service(monkeypatch):
    from agentmind.routing.side_effects.trace_recorder import TraceRecorder
    import agentmind.routing.side_effects.trace_recorder as trace_recorder

    calls = []

    class FakeTraceService:
        async def record_decision(self, trace_id, decision, user_id=""):
            calls.append(("record", trace_id, decision.agent_id, user_id))

        async def get_trace(self, trace_id):
            calls.append(("get", trace_id))
            return {"trace_id": trace_id}

    monkeypatch.setattr(trace_recorder, "TraceService", FakeTraceService)

    await TraceRecorder.record_decision("t1", _decision(), "u1")

    assert await TraceRecorder.get_trace("t1") == {"trace_id": "t1"}
    assert ("record", "t1", "a1", "u1") in calls
    assert ("get", "t1") in calls


def test_panel_routing_trace_uses_trace_service(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from agentmind.panel.server import create_panel_router

    class FakeTraceService:
        async def get_trace(self, trace_id):
            return {"trace_id": trace_id, "summary": "from service"}

    monkeypatch.setattr("agentmind.panel.server.TraceService", FakeTraceService, raising=False)

    app = FastAPI()
    app.include_router(create_panel_router(), prefix="/panel/api")
    client = TestClient(app)

    resp = client.get("/panel/api/routing/trace/t1")

    assert resp.status_code == 200
    assert resp.json()["summary"] == "from service"
