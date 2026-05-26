# AgentMind Phase 1 Routing Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the `/v1/route` request entrypoint and `route_stream` orchestration into a dedicated routing service module while preserving existing routing behavior and keeping memory work out of scope.

**Architecture:** Keep `src/agentmind/api/router.py` as the FastAPI router surface, but move the request orchestration, attach handling, orchestration dispatch, discussion flow, and streaming route logic into a new service module. The router file should become a thin adapter that forwards requests into the service. Preserve the current pipeline, task recording, and memory side effects exactly so the existing tests continue to pass.

**Tech Stack:** Python 3.12, FastAPI, SSE, asyncio, pytest, pytest-asyncio.

---

## Current Baseline

- `Phase 1` startup convergence is complete and green.
- Reported full-suite baseline:

```bash
pytest -q
```

Expected baseline:

```text
344 passed, 4 warnings
```

## Files

Create:

- `src/agentmind/services/routing_service.py`
- `tests/test_routing_service.py`

Modify:

- `src/agentmind/api/router.py`
- `tests/test_router.py`
- `tests/test_stream.py`

Do not modify in this package:

- `src/agentmind/storage/memory.py`
- `src/agentmind/memory/service.py`
- `src/agentmind/main.py`
- `src/agentmind/startup.py`

## Strict Testing Rules

Every production change follows RED-GREEN:

1. Add or update a focused failing test.
2. Run that exact test and confirm it fails for the expected reason.
3. Implement the smallest production change.
4. Run the exact test and confirm it passes.
5. Run the package verification commands.
6. Commit the task.

Package verification commands:

```bash
pytest tests/test_routing_service.py -q
pytest tests/test_router.py tests/test_stream.py -q
pytest -q
```

---

### Task 1: Add a routing service seam and direct service tests

**Files:**

- Create: `tests/test_routing_service.py`
- Create: `src/agentmind/services/routing_service.py`

- [ ] **Step 1: Write the failing routing service tests**

Create `tests/test_routing_service.py` with a seam test that proves the service can expose the current route entrypoint behavior without importing `api/router.py` directly:

```python
import tempfile
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI

from agentmind.agents.registry import AgentRegistry
from agentmind.core.rule_engine import RuleEngine
from agentmind.services.routing_service import RoutingService


def build_app(tmp_dir: Path):
    agents_path = tmp_dir / "config" / "agents.yaml"
    routes_path = tmp_dir / "config" / "routes.yaml"
    agents_path.parent.mkdir(parents=True, exist_ok=True)
    agents_path.write_text(
        yaml.dump({
            "agents": [
                {"id": "mock_echo", "name": "Mock Echo", "type": "cli", "tags": ["general"], "enabled": True, "timeout": 5,
                 "config": {"command": "echo done", "health_check": "echo ok"}},
            ]
        }, allow_unicode=True),
        encoding="utf-8",
    )
    routes_path.write_text(yaml.dump({"rules": []}, allow_unicode=True), encoding="utf-8")
    registry = AgentRegistry(agents_path)
    for ex in registry.executors.values():
        ex.is_healthy = True
    engine = RuleEngine(routes_path, agent_registry=registry)
    app = FastAPI()
    app.state.agent_registry = registry
    app.state.rule_engine = engine
    app.state.settings = {"routing": {"use_new_pipeline": True}}
    return app


@pytest.mark.asyncio
async def test_routing_service_route_request_returns_decision(tmp_path):
    app = build_app(tmp_path)
    service = RoutingService(app)

    result = await service.route_request({"message": "写一个函数", "stream": False})

    assert result["agent_id"] == "mock_echo"
    assert "trace_id" in result
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_routing_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentmind.services.routing_service'`.

- [ ] **Step 3: Implement the routing service seam**

Create `src/agentmind/services/routing_service.py`:

```python
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from agentmind.api.models import RouteRequest
from agentmind.core.trace import generate_trace_id
from agentmind.storage.db import record_attached_turn, record_task_end, record_task_start, record_task_update
from agentmind.storage.memory import write_memory

logger = logging.getLogger("agentmind")


class RoutingService:
    def __init__(self, app):
        self.app = app

    async def route_request(self, payload: dict[str, Any], request: Request | None = None):
        route_req = RouteRequest(**payload)
        request = request or self.app
        return await _route_request_impl(route_req, request)


async def _route_request_impl(route_req: RouteRequest, request: Request):
    from agentmind.api.router import (
        _execute_orchestration_plan,
        _is_new_session_cmd,
        _match_orchestration,
        _parse_discussion,
        _resolve_agent_mention,
        _run_discussion,
        _step_security_intercept,
    )
    from agentmind.memory.service import MemoryService
    from agentmind.routing.context import RequestIdentity
    from agentmind.routing.executors.self_reply import SelfReplyExecutor
    from agentmind.routing.executors.single_agent import SingleAgentExecutor
    from agentmind.routing.pipeline import RoutingPipeline
    from agentmind.routing.side_effects.trace_recorder import TraceRecorder

    if _is_new_session_cmd(route_req.message):
        try:
            sid = await MemoryService().new_session(route_req.user_id or "")
            return JSONResponse(content={
                "agent_id": "agentmind",
                "result": f"已开启新会话 ({sid})，Working Memory 已清空",
                "trace_id": generate_trace_id(),
                "status": "completed",
            })
        except Exception as e:
            logger.warning("/new 会话创建失败: %s", e)
            return JSONResponse(status_code=500, content={
                "error": f"会话创建失败: {e}",
                "trace_id": generate_trace_id(),
            })

    plan = _match_orchestration(route_req.message)
    if plan:
        agent_registry = request.app.state.agent_registry
        return EventSourceResponse(_execute_orchestration_plan(plan, route_req.user_id or "", agent_registry, None, route_req.message))

    if route_req.session_id:
        attach_registry = getattr(request.app.state, "attach_registry", None)
        if attach_registry:
            bound_tid = attach_registry.get_bound_task(route_req.session_id)
            if bound_tid:
                return await _handle_attached_command(bound_tid, route_req, request)

    trace_id = generate_trace_id()
    msg = route_req.message
    agent_registry = request.app.state.agent_registry
    engine = request.app.state.rule_engine
    settings = getattr(request.app.state, "settings", None) or {}

    security_agent_id = _step_security_intercept(msg, agent_registry)
    await record_task_start(trace_id, msg)
    await record_task_update(trace_id, status="routing")

    identity = RequestIdentity(
        trace_id=trace_id,
        user_id=route_req.user_id or "",
        session_id=route_req.session_id or "",
    )
    pipeline = RoutingPipeline(agent_registry, engine)
    decision = await pipeline.run(msg, identity, settings, route_req.is_retry)

    if decision is not None:
        await record_task_update(trace_id, status="routing", matched_rule=decision.strategy or "pipeline", routed_agent=decision.agent_id)
        await TraceRecorder.record_decision(trace_id, decision, route_req.user_id or "")

        if not decision.agent_id:
            await record_task_end(trace_id, "failed", error_message="无可用Agent")
            if route_req.stream:
                async def _no_agent_sse():
                    yield {"event": "error", "data": json.dumps({
                        "error": "没有可用的 Agent，请检查 Agent 是否已安装并启用",
                        "trace_id": trace_id,
                    })}
                return EventSourceResponse(_no_agent_sse())
            return JSONResponse(status_code=503, content={
                "error": "没有可用的 Agent，请检查 Agent 是否已安装并启用",
                "trace_id": trace_id,
            })

        if decision.agent_id == "agentmind":
            executor = SelfReplyExecutor(agent_registry)
        else:
            executor = SingleAgentExecutor(agent_registry)

        if route_req.stream:
            return EventSourceResponse(executor.run_stream(decision, trace_id, route_req.user_id or ""))
        return await executor.run_json(decision, trace_id, route_req.user_id or "")

    return JSONResponse(status_code=500, content={"error": "routing failed", "trace_id": trace_id})


async def _handle_attached_command(trace_id: str, route_req: RouteRequest, request: Request):
    from agentmind.api.router import handle_attached_command

    return await handle_attached_command(trace_id, route_req, request)
```

- [ ] **Step 4: Run the focused test**

Run:

```bash
pytest tests/test_routing_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentmind/services/routing_service.py tests/test_routing_service.py
git commit -m "feat: add routing service seam"
```

---

### Task 2: Move `/v1/route` and `route_stream` orchestration behind the service

**Files:**

- Modify: `src/agentmind/api/router.py`
- Modify: `tests/test_router.py`
- Modify: `tests/test_stream.py`

- [ ] **Step 1: Add a failing integration test for the new entrypoint**

Add a focused router test that patches `RoutingService.route_request` and confirms the FastAPI route forwards to it:

```python
from unittest.mock import AsyncMock


def test_route_endpoint_delegates_to_routing_service(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        app, mp = make_test_app(tmp_dir)
        client = TestClient(app)
        calls = []

        async def fake_route_request(payload, request=None):
            calls.append(payload)
            return {"agent_id": "mock_echo", "trace_id": "tr-x"}

        try:
            mp.setattr("agentmind.services.routing_service.RoutingService.route_request", fake_route_request)
            resp = client.post("/v1/route", json={"message": "写一个函数", "stream": False})
            assert resp.status_code == 200
            assert calls and calls[0]["message"] == "写一个函数"
        finally:
            mp.undo()
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_router.py::TestRouteNonStream::test_non_stream_returns_json -q
```

Expected: fail until `src/agentmind/api/router.py` forwards through the service.

- [ ] **Step 3: Replace router body with service delegation**

Modify `src/agentmind/api/router.py` so `route_request()` and `route_stream()` forward into `RoutingService`, while keeping helper functions in place for compatibility during the transition.

The router module should keep:

```python
router = APIRouter()
```

and the existing helper functions used by the service, but the main request path should become a delegation layer instead of owning orchestration.

- [ ] **Step 4: Run the router and stream tests**

Run:

```bash
pytest tests/test_router.py tests/test_stream.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentmind/api/router.py tests/test_router.py tests/test_stream.py
git commit -m "refactor: delegate route orchestration to service"
```

---

### Task 3: Verify package integrity and keep memory scope out

**Files:**

- Modify: `tests/test_router.py` if a regression check is needed

- [ ] **Step 1: Run package verification**

Run:

```bash
pytest tests/test_routing_service.py -q
pytest tests/test_router.py tests/test_stream.py -q
pytest -q
```

Expected:

```text
full suite remains green
```

- [ ] **Step 2: Check scope boundaries**

Confirm this package did not introduce:

```text
memory service unification
trace storage redesign
new session persistence semantics
panel changes
main.py changes
```

- [ ] **Step 3: Commit the package**

```bash
git add src/agentmind/services/routing_service.py src/agentmind/api/router.py tests/test_routing_service.py tests/test_router.py tests/test_stream.py
git commit -m "refactor: extract routing service boundary"
```

## Self-Review

- Spec coverage: Covers the Phase 1 `RoutingService` subpackage only, with request entrypoint extraction and delegation.
- Intentional gaps: memory unification, trace split, panel refactors, and any changes to routing semantics remain out of scope.
- Placeholder scan: No placeholders or vague tasks remain.
- Type consistency: `RoutingService.route_request(payload, request=None)` is used consistently in tests and implementation notes.
