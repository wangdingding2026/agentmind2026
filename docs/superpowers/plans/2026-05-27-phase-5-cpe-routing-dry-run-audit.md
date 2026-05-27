# Phase 5 CPE Routing Dry-Run Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record CPE dry-run audit events from the HTTP RoutingService path after routing decisions are made, without changing route behavior.

**Architecture:** RoutingService remains the service-layer caller for route-request governance. This package calls default-allow CPE after a routing decision exists, records the decision with `AuditService.record_cpe_decision`, and deliberately ignores the CPE result for behavior. Panel/API/channel handlers remain adapters; `RoutingPipeline`, `SensitiveScanner`, and `CandidatePool` remain unchanged.

**Tech Stack:** Python async helpers, existing `CPE`, existing `AuditService`, pytest unit tests, FastAPI route tests.

---

## Scope

Modify:

- `src/agentmind/services/routing_service.py`
- `tests/test_cpe_routing_entrypoint.py`
- `tests/test_governance_skeleton.py`
- `docs/phase5/phase-5-readiness.md`

Create:

- `docs/superpowers/plans/2026-05-27-phase-5-cpe-routing-dry-run-audit.md`

Do not modify `RoutingPipeline`, `SensitiveScanner`, `CandidatePool`, memory retrieval, panel, channels, executors, or Feishu fallback code.

## Behavior

For HTTP `RoutingService` / `/v1/route` non-stream and stream requests:

1. existing routing behavior runs first;
2. once `decision.agent_id` is available, RoutingService builds a `CPERequest`;
3. RoutingService calls `CPE().evaluate(...)`;
4. RoutingService records the CPE decision through `AuditService.record_cpe_decision(...)`;
5. failures in dry-run CPE/audit are logged at debug level and do not affect the response;
6. CPE decisions do not block, reroute, or require approval in this package.

This package does not wire CPE into `route_stream`.

## Non-Goals

- Do not change routing decisions.
- Do not block cloud agents.
- Do not require user approval.
- Do not replace sensitive scanning.
- Do not gate private memory retrieval.
- Do not add AgentShield behavior.
- Do not record CPE dry-run from channel paths or `route_stream`.

## Task 1: RED Dry-Run Audit Tests

**Files:**
- Modify: `tests/test_cpe_routing_entrypoint.py`
- Modify: `tests/test_governance_skeleton.py`

- [ ] **Step 1: Add dry-run unit test**

Append to `tests/test_cpe_routing_entrypoint.py`:

```python
import pytest


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
```

- [ ] **Step 2: Add architecture assertion for dry-run only**

Update `tests/test_governance_skeleton.py::test_routing_service_only_has_cpe_request_builder_seam` to also allow `_record_cpe_routing_dry_run`, while still asserting no blocking behavior:

```python
def test_routing_service_only_has_cpe_request_builder_seam():
    text = ROUTER_SERVICE.read_text(encoding="utf-8")

    assert "agentmind.governance" in text
    assert "def _build_cpe_request_for_routing" in text
    assert "def _record_cpe_routing_dry_run" in text
    assert "record_cpe_decision" in text
    assert "raise HTTPException" not in text
    assert "CPE decision: block" not in text
```

- [ ] **Step 3: Run RED**

```bash
pytest tests/test_cpe_routing_entrypoint.py::test_routing_service_records_cpe_dry_run_decision tests/test_governance_skeleton.py::test_routing_service_only_has_cpe_request_builder_seam -q
```

Expected: FAIL because `_record_cpe_routing_dry_run`, `CPE`, and `AuditService` are not present in `routing_service`.

## Task 2: GREEN Dry-Run Helper

**Files:**
- Modify: `src/agentmind/services/routing_service.py`

- [ ] **Step 1: Import CPE and AuditService**

Change:

```python
from agentmind.governance import CPERequest
```

to:

```python
from agentmind.governance import CPE, CPERequest
from agentmind.services.audit_service import AuditService
```

- [ ] **Step 2: Add dry-run helper**

Add after `_build_cpe_request_for_routing`:

```python
async def _record_cpe_routing_dry_run(cpe_request: CPERequest) -> None:
    try:
        decision = CPE().evaluate(cpe_request)
        await AuditService().record_cpe_decision(
            request=cpe_request,
            decision=decision,
            actor="system",
            payload={"surface": "routing", "mode": "dry_run"},
        )
    except Exception:
        logger.debug("记录 CPE routing dry-run audit 失败", exc_info=True)
```

- [ ] **Step 3: Run GREEN helper test**

```bash
pytest tests/test_cpe_routing_entrypoint.py::test_routing_service_records_cpe_dry_run_decision tests/test_governance_skeleton.py::test_routing_service_only_has_cpe_request_builder_seam -q
```

Expected: PASS.

## Task 3: Wire Dry-Run Into HTTP RoutingService Path

**Files:**
- Modify: `src/agentmind/services/routing_service.py`
- Modify: `tests/test_cpe_routing_entrypoint.py`

- [ ] **Step 1: Add route-request integration test**

Append to `tests/test_cpe_routing_entrypoint.py`:

```python
@pytest.mark.asyncio
async def test_route_request_records_cpe_dry_run_without_changing_decision(monkeypatch):
    from agentmind.routing.context import RequestIdentity, RoutingContext, RoutingDecision
    from agentmind.services import routing_service

    calls = []

    class FakePipeline:
        def __init__(self, agent_registry, engine):
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
```

Add imports at the top of `tests/test_cpe_routing_entrypoint.py`:

```python
import json
from unittest.mock import AsyncMock

from fastapi.responses import JSONResponse
```

- [ ] **Step 2: Run RED integration test**

```bash
pytest tests/test_cpe_routing_entrypoint.py::test_route_request_records_cpe_dry_run_without_changing_decision -q
```

Expected: FAIL because `_route_request_impl` does not call `_record_cpe_routing_dry_run`.

- [ ] **Step 3: Call dry-run helper after route decision audit**

In `_route_request_impl`, after `TraceRecorder.record_decision(...)`, add:

```python
        await _record_cpe_routing_dry_run(
            _build_cpe_request_for_routing(
                trace_id=trace_id,
                user_id=route_req.user_id or "",
                agent_id=decision.agent_id,
                message=msg,
                agent_registry=agent_registry,
                memories=decision.context.memories if decision.context else [],
            )
        )
```

- [ ] **Step 4: Run GREEN integration test**

```bash
pytest tests/test_cpe_routing_entrypoint.py::test_route_request_records_cpe_dry_run_without_changing_decision -q
```

Expected: PASS.

## Task 4: Update Phase 5 Readiness

**Files:**
- Modify: `docs/phase5/phase-5-readiness.md`

- [ ] **Step 1: Document dry-run scope**

Add:

```markdown
RoutingService records CPE dry-run audit events for HTTP route requests after routing decisions are made. These events do not block, reroute, or require approval.
```

- [ ] **Step 2: Run focused tests**

```bash
pytest tests/test_cpe_routing_entrypoint.py tests/test_governance_skeleton.py tests/test_phase5_readiness_audit.py -q
```

Expected: PASS.

## Task 5: Regression Verification

**Files:**
- Test only.

- [ ] **Step 1: Run focused governance/routing tests**

```bash
pytest tests/test_cpe_routing_entrypoint.py tests/test_governance_skeleton.py tests/test_audit_service.py tests/test_phase5_readiness_audit.py -q
```

Expected: PASS.

- [ ] **Step 2: Run routing-related regression**

```bash
pytest tests/test_router.py tests/test_pipeline_executors.py tests/test_e2e_scenarios.py -q
```

Expected: PASS.

- [ ] **Step 3: Run panel/architecture regression**

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py tests/test_phase4_closure_audit.py tests/test_phase5_readiness_audit.py -q
```

Expected: PASS.

- [ ] **Step 4: Run router/panel regression**

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full verification**

```bash
pytest -q
git diff --check
git status --short
```

Expected: pytest passes, diff check is clean, and status only shows this package before commit.

## Task 6: Commit

**Files:**
- `docs/superpowers/plans/2026-05-27-phase-5-cpe-routing-dry-run-audit.md`
- `docs/phase5/phase-5-readiness.md`
- `src/agentmind/services/routing_service.py`
- `tests/test_cpe_routing_entrypoint.py`
- `tests/test_governance_skeleton.py`

- [ ] **Step 1: Commit**

```bash
git add docs/superpowers/plans/2026-05-27-phase-5-cpe-routing-dry-run-audit.md docs/phase5/phase-5-readiness.md src/agentmind/services/routing_service.py tests/test_cpe_routing_entrypoint.py tests/test_governance_skeleton.py
git commit -m "feat: record cpe routing dry-run audit"
```

## Self-Review

- Spec coverage: Covers only HTTP RoutingService dry-run audit.
- Placeholder scan: No placeholders.
- Type consistency: Uses existing `CPE`, `CPERequest`, and `AuditService.record_cpe_decision`.
