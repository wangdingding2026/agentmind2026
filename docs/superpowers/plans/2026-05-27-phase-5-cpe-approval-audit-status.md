# Phase 5 CPE Approval Audit Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep CPE `require_approval` audit events distinguishable from hard `block` events, especially while routing remains dry-run only.

**Architecture:** CPE owns the decision status. AuditService owns persistence and query shape for governance events. RoutingService remains a service caller that records dry-run CPE decisions and does not enforce approval or block behavior.

**Tech Stack:** Python enums/dataclasses, AuditService SQLite event storage, pytest async tests.

---

## Scope

Modify:

- `src/agentmind/services/audit_service.py`
- `tests/test_audit_service.py`
- `tests/test_cpe_routing_entrypoint.py`
- `docs/phase5/phase-5-readiness.md`

Create:

- `docs/superpowers/plans/2026-05-27-phase-5-cpe-approval-audit-status.md`

Do not modify:

- Routing enforcement behavior
- RoutingPipeline
- CandidatePool
- SensitiveScanner
- memory retrieval
- panel/channel adapters

## Behavior

CPE audit event row status should map as:

- `allow` -> `success`
- `require_approval` -> `approval_required`
- `block` -> `blocked`

Routing dry-run CPE events should continue to include payload `{"surface": "routing", "mode": "dry_run"}` and should not block or reroute.

## Task 1: RED Audit Status Test

**Files:**

- Modify: `tests/test_audit_service.py`

- [ ] **Step 1: Update approval-required expectation**

In `test_audit_service_record_cpe_decision_helper`, change:

```python
assert events[0]["status"] == "blocked"
```

to:

```python
assert events[0]["status"] == "approval_required"
```

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_audit_service.py::test_audit_service_record_cpe_decision_helper -q
```

Expected: FAIL because AuditService still stores every non-allow CPE decision as `blocked`.

## Task 2: RED Routing Dry-Run Visibility Test

**Files:**

- Modify: `tests/test_cpe_routing_entrypoint.py`

- [ ] **Step 1: Add dry-run approval audit test**

Append:

```python
@pytest.mark.asyncio
async def test_routing_cpe_dry_run_records_approval_required_for_sensitive_cloud(monkeypatch):
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
    assert decision.status.value == "require_approval"
    assert decision.risk_level == "high"
    assert calls["audit"]["payload"] == {"surface": "routing", "mode": "dry_run"}
```

- [ ] **Step 2: Run RED with both tests**

```bash
pytest tests/test_audit_service.py::test_audit_service_record_cpe_decision_helper tests/test_cpe_routing_entrypoint.py::test_routing_cpe_dry_run_records_approval_required_for_sensitive_cloud -q
```

Expected: one failure from AuditService status mapping; the routing dry-run visibility test may already pass because CPE policy v1 exists.

## Task 3: GREEN Audit Status Mapping

**Files:**

- Modify: `src/agentmind/services/audit_service.py`

- [ ] **Step 1: Add status mapper**

Replace:

```python
status = "success" if decision_status == "allow" else "blocked"
```

with:

```python
status = self._cpe_event_status(decision_status)
```

Add:

```python
    def _cpe_event_status(self, decision_status: str) -> str:
        if decision_status == "allow":
            return "success"
        if decision_status == "require_approval":
            return "approval_required"
        return "blocked"
```

- [ ] **Step 2: Run GREEN focused tests**

```bash
pytest tests/test_audit_service.py::test_audit_service_record_cpe_decision_helper tests/test_cpe_routing_entrypoint.py::test_routing_cpe_dry_run_records_approval_required_for_sensitive_cloud -q
```

Expected: PASS.

## Task 4: Update Phase 5 Readiness

**Files:**

- Modify: `docs/phase5/phase-5-readiness.md`

- [ ] **Step 1: Document audit status semantics**

Add:

```markdown
CPE audit event row status distinguishes `approval_required` from hard `blocked` decisions, so dry-run routing governance visibility cannot be mistaken for enforcement.
```

- [ ] **Step 2: Run package verification**

```bash
pytest tests/test_audit_service.py tests/test_cpe_routing_entrypoint.py tests/test_governance_skeleton.py tests/test_phase5_readiness_audit.py -q
pytest tests/test_router.py tests/test_pipeline_executors.py tests/test_e2e_scenarios.py -q
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py tests/test_phase4_closure_audit.py tests/test_phase5_readiness_audit.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
git diff --check
git status --short
```

## Task 5: Commit

**Files:**

- Commit all changed files.

- [ ] **Step 1: Commit**

```bash
git add src/agentmind/services/audit_service.py tests/test_audit_service.py tests/test_cpe_routing_entrypoint.py docs/phase5/phase-5-readiness.md docs/superpowers/plans/2026-05-27-phase-5-cpe-approval-audit-status.md
git commit -m "feat: distinguish cpe approval audit status"
```
