# Phase 5 CPE Audit Event Shape Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the AuditService event helper and tests that define how CPE decisions are recorded, without wiring CPE into routing or memory retrieval.

**Architecture:** `agentmind.governance` owns CPE decisions, while `AuditService` owns persistence and query shape. This package adds a service helper that accepts a `GovernanceDecision` and records a normalized `governance/cpe_decision` audit event. Runtime services will call this helper in later packages.

**Tech Stack:** Python dataclasses/enums, SQLite-backed `AuditService`, pytest async tests, Markdown phase docs.

---

## Scope

Modify:

- `src/agentmind/services/audit_service.py`
- `tests/test_audit_service.py`
- `docs/phase5/phase-5-readiness.md`

Create:

- `docs/superpowers/plans/2026-05-27-phase-5-cpe-audit-event-shape.md`

Do not modify routing, memory retrieval, panel, channels, or executors.

## Event Shape

`AuditService.record_cpe_decision(...)` records:

- `module="governance"`
- `action="cpe_decision"`
- `trace_id` from the request
- `user_id` from the request
- `agent_id` from the request
- `risk_level` from `GovernanceDecision.risk_level`
- `status="success"` for `ALLOW`
- `status="blocked"` for `BLOCK` and `REQUIRE_APPROVAL`
- `message="CPE decision: <status>"`

Payload contains:

- `component="CPE"`
- `decision_status`
- `reason`
- `agent_security_level`
- `memory_count`
- all keys from `GovernanceDecision.audit_payload`
- all keys from optional caller payload

## Non-Goals

- Do not call this helper from routing.
- Do not call this helper from memory retrieval.
- Do not add CPE policy logic.
- Do not add approval workflow.
- Do not add AgentShield audit helper in this package.
- Do not alter existing routing audit event shape.

## Task 1: RED AuditService CPE Decision Tests

**Files:**
- Modify: `tests/test_audit_service.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_audit_service.py`:

```python
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
    assert events[0]["status"] == "blocked"
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
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_audit_service.py::test_audit_service_record_cpe_decision_helper -q
```

Expected: FAIL with `AttributeError: 'AuditService' object has no attribute 'record_cpe_decision'`.

## Task 2: GREEN AuditService Helper

**Files:**
- Modify: `src/agentmind/services/audit_service.py`

- [ ] **Step 1: Add `record_cpe_decision`**

Add this method after `record_routing_decision`:

```python
    async def record_cpe_decision(
        self,
        *,
        request,
        decision,
        actor: str = "system",
        payload: dict[str, Any] | None = None,
    ) -> str:
        decision_status = getattr(decision.status, "value", str(decision.status))
        event_payload = {
            "component": "CPE",
            "decision_status": decision_status,
            "reason": decision.reason,
            "agent_security_level": request.agent_security_level,
            "memory_count": len(request.memory_items),
        }
        event_payload.update(decision.audit_payload or {})
        event_payload.update(payload or {})
        status = "success" if decision_status == "allow" else "blocked"
        return await self.record_event(
            module="governance",
            action="cpe_decision",
            actor=actor,
            user_id=request.user_id,
            trace_id=request.trace_id,
            agent_id=request.agent_id,
            risk_level=decision.risk_level,
            status=status,
            message=f"CPE decision: {decision_status}",
            payload=event_payload,
        )
```

- [ ] **Step 2: Run GREEN focused test**

```bash
pytest tests/test_audit_service.py::test_audit_service_record_cpe_decision_helper -q
```

Expected: PASS.

## Task 3: Update Phase 5 Readiness

**Files:**
- Modify: `docs/phase5/phase-5-readiness.md`

- [ ] **Step 1: Record CPE audit shape**

Add a short note under CPE start criteria or Next Direction:

```markdown
The CPE audit event shape is `module=governance`, `action=cpe_decision`, with `decision_status`, `reason`, `agent_security_level`, and `memory_count` in payload.
```

- [ ] **Step 2: Run readiness/governance focused tests**

```bash
pytest tests/test_audit_service.py::test_audit_service_record_cpe_decision_helper tests/test_governance_skeleton.py tests/test_phase5_readiness_audit.py -q
```

Expected: PASS.

## Task 4: Regression Verification

**Files:**
- Test only.

- [ ] **Step 1: Run focused tests**

```bash
pytest tests/test_audit_service.py tests/test_governance_skeleton.py tests/test_phase5_readiness_audit.py -q
```

Expected: PASS.

- [ ] **Step 2: Run architecture closure tests**

```bash
pytest tests/test_phase5_readiness_audit.py tests/test_phase4_closure_audit.py tests/test_phase3_closure_audit.py -q
```

Expected: PASS.

- [ ] **Step 3: Run related module regression**

```bash
pytest tests/test_audit_service.py tests/test_config_service.py tests/test_routing_explanation_service.py tests/test_task_explanation_service.py -q
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
- `docs/superpowers/plans/2026-05-27-phase-5-cpe-audit-event-shape.md`
- `docs/phase5/phase-5-readiness.md`
- `src/agentmind/services/audit_service.py`
- `tests/test_audit_service.py`

- [ ] **Step 1: Commit**

```bash
git add docs/superpowers/plans/2026-05-27-phase-5-cpe-audit-event-shape.md docs/phase5/phase-5-readiness.md src/agentmind/services/audit_service.py tests/test_audit_service.py
git commit -m "feat: add cpe audit event shape"
```

## Self-Review

- Spec coverage: Covers only CPE audit event shape.
- Placeholder scan: No placeholders.
- Type consistency: Uses existing `GovernanceDecision` and `CPERequest` contracts.
