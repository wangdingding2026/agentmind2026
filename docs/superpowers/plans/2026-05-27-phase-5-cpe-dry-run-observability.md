# Phase 5 CPE Dry-Run Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface CPE dry-run audit events in existing routing/task explanation views without adding new panel policy logic or changing CPE behavior.

**Architecture:** `AuditService` remains the only audit query boundary. `RoutingExplanationService` already aggregates trace-scoped audit events; this package adds a derived `governance_events` field filtered from those service-returned audit events. Panel handlers continue to delegate to services and do not inspect CPE internals.

**Tech Stack:** Python service tests, existing `RoutingExplanationService`, existing `TaskExplanationService`, existing panel audit query endpoint, pytest.

---

## Scope

Modify:

- `src/agentmind/services/routing_explanation_service.py`
- `tests/test_routing_explanation_service.py`
- `tests/test_task_explanation_service.py`
- `tests/test_panel_api.py`
- `docs/phase5/phase-5-readiness.md`

Create:

- `docs/superpowers/plans/2026-05-27-phase-5-cpe-dry-run-observability.md`

Do not modify `AuditService.query_events`, panel routing logic, CPE policy behavior, routing decisions, memory retrieval, or channel code.

## Behavior

- Routing explanations include all trace audit events as before.
- Routing explanations also include `governance_events`, filtered from `audit_events` where `module == "governance"`.
- CPE dry-run events remain plain audit events with `action == "cpe_decision"`.
- Task explanations inherit routing explanations and still query task-scoped audit events through `AuditService`.
- Panel endpoints remain thin adapters.

## Non-Goals

- Do not add a new panel endpoint.
- Do not make panel parse CPE payloads.
- Do not change `AuditService.query_events` filtering semantics.
- Do not change RoutingService dry-run behavior.
- Do not implement blocking, approval, reroute, or memory gating.

## Task 1: RED Routing Explanation Governance Events

**Files:**
- Modify: `tests/test_routing_explanation_service.py`
- Modify: `tests/test_task_explanation_service.py`
- Modify: `tests/test_panel_api.py`

- [ ] **Step 1: Update routing explanation fake audit events**

In `tests/test_routing_explanation_service.py`, update `_AuditService.query_events` to return both routing and governance events:

```python
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
```

Then assert:

```python
assert explanation["governance_events"] == [
    {
        "event_id": "e2",
        "trace_id": "t1",
        "module": "governance",
        "action": "cpe_decision",
        "payload": {"decision_status": "allow", "mode": "dry_run"},
    }
]
```

Also add `"governance_events": []` to the missing trace expected result.

- [ ] **Step 2: Update task explanation fake routing result**

In `tests/test_task_explanation_service.py`, update `_RoutingExplanationService.explain` to include:

```python
"governance_events": [{"event_id": "e2", "module": "governance"}],
```

Assert:

```python
assert explanation["routing"]["governance_events"] == [
    {"event_id": "e2", "module": "governance"}
]
```

- [ ] **Step 3: Add panel endpoint pass-through assertion**

In `tests/test_panel_api.py::test_routing_explanation_endpoint_uses_service`, make the fake service return a `governance_events` field and assert the response preserves it.

- [ ] **Step 4: Run RED**

```bash
pytest tests/test_routing_explanation_service.py tests/test_task_explanation_service.py tests/test_panel_api.py::TestPanelAPI::test_routing_explanation_endpoint_uses_service -q
```

Expected: FAIL because `RoutingExplanationService` does not include `governance_events`.

## Task 2: GREEN RoutingExplanationService

**Files:**
- Modify: `src/agentmind/services/routing_explanation_service.py`

- [ ] **Step 1: Reuse audit events and derive governance events**

In `explain`, store audit events once:

```python
audit_events = await self._audit_events(trace_id)
```

Return both:

```python
"audit_events": audit_events,
"governance_events": self._governance_events(audit_events),
```

Add:

```python
    def _governance_events(self, audit_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [event for event in audit_events if event.get("module") == "governance"]
```

Add `"governance_events": []` to `_missing`.

- [ ] **Step 2: Run GREEN focused tests**

```bash
pytest tests/test_routing_explanation_service.py tests/test_task_explanation_service.py tests/test_panel_api.py::TestPanelAPI::test_routing_explanation_endpoint_uses_service -q
```

Expected: PASS.

## Task 3: Update Phase 5 Readiness

**Files:**
- Modify: `docs/phase5/phase-5-readiness.md`

- [ ] **Step 1: Document observability scope**

Add:

```markdown
RoutingExplanationService exposes CPE dry-run audit visibility as `governance_events`, derived from AuditService trace events. Panel endpoints remain pass-through adapters.
```

- [ ] **Step 2: Run focused tests**

```bash
pytest tests/test_routing_explanation_service.py tests/test_task_explanation_service.py tests/test_phase5_readiness_audit.py -q
```

Expected: PASS.

## Task 4: Regression Verification

**Files:**
- Test only.

- [ ] **Step 1: Run focused observability tests**

```bash
pytest tests/test_routing_explanation_service.py tests/test_task_explanation_service.py tests/test_panel_api.py::TestPanelAPI::test_audit_events_endpoint_uses_audit_service tests/test_panel_api.py::TestPanelAPI::test_routing_explanation_endpoint_uses_service -q
```

Expected: PASS.

- [ ] **Step 2: Run governance/readiness tests**

```bash
pytest tests/test_cpe_routing_entrypoint.py tests/test_governance_skeleton.py tests/test_audit_service.py tests/test_phase5_readiness_audit.py -q
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

## Task 5: Commit

**Files:**
- `docs/superpowers/plans/2026-05-27-phase-5-cpe-dry-run-observability.md`
- `docs/phase5/phase-5-readiness.md`
- `src/agentmind/services/routing_explanation_service.py`
- `tests/test_routing_explanation_service.py`
- `tests/test_task_explanation_service.py`
- `tests/test_panel_api.py`

- [ ] **Step 1: Commit**

```bash
git add docs/superpowers/plans/2026-05-27-phase-5-cpe-dry-run-observability.md docs/phase5/phase-5-readiness.md src/agentmind/services/routing_explanation_service.py tests/test_routing_explanation_service.py tests/test_task_explanation_service.py tests/test_panel_api.py
git commit -m "feat: expose cpe dry-run governance events"
```

## Self-Review

- Spec coverage: Covers only query/explanation visibility for existing CPE dry-run audit events.
- Placeholder scan: No placeholders.
- Type consistency: Uses existing `audit_events` and adds derived `governance_events`.
