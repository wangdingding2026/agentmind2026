# Phase 5 CPE Permissive No Content Inspection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep CPE/AuditService/RoutingService architecture seams in place while disabling customer-content inspection for early free-use behavior.

**Architecture:** CPE remains the information-flow decision boundary, but its current runtime policy is permissive and does not inspect customer message content. RoutingService may still build a CPE request and record dry-run governance metadata after routing, but no CPE result blocks, reroutes, requires approval, or classifies customer content.

**Tech Stack:** Python governance dataclasses, pytest TDD tests, existing routing dry-run audit seam.

---

## Scope

Modify:

- `src/agentmind/governance/cpe.py`
- `tests/test_governance_skeleton.py`
- `tests/test_cpe_routing_entrypoint.py`
- `docs/phase5/phase-5-readiness.md`

Create:

- `docs/superpowers/plans/2026-05-27-phase-5-cpe-permissive-no-content-inspection.md`

Do not modify:

- Routing enforcement behavior
- RoutingPipeline
- CandidatePool
- SensitiveScanner legacy routing middleware
- memory retrieval
- panel/channel adapters
- approval UI

## Behavior

Current Phase 5 CPE behavior:

- always returns `ALLOW`;
- uses `risk_level="low"`;
- does not scan `request.context["message"]`;
- does not emit `sensitive_context`;
- emits `content_inspection=False` and `policy="permissive-no-content-inspection"` as metadata;
- leaves AuditService decision status mapping available for future policy packages.

## Task 1: RED CPE No-Inspection Tests

**Files:**

- Modify: `tests/test_governance_skeleton.py`

- [ ] **Step 1: Update default CPE expectation**

In `test_cpe_default_decision_contract_allows_without_runtime_policy`, replace the sensitive-context assertion with:

```python
assert decision.audit_payload["content_inspection"] is False
assert decision.audit_payload["policy"] == "permissive-no-content-inspection"
assert "sensitive_context" not in decision.audit_payload
```

- [ ] **Step 2: Replace sensitive approval tests**

Replace `test_cpe_requires_approval_for_sensitive_context_to_cloud_agent` and `test_cpe_allows_sensitive_context_to_local_agent` with:

```python
def test_cpe_does_not_inspect_customer_message_content_by_default():
    from agentmind.governance import CPE, CPERequest, GovernanceDecisionStatus

    decision = CPE().evaluate(
        CPERequest(
            trace_id="t-customer-content",
            user_id="u1",
            agent_id="cloud_agent",
            agent_security_level="cloud",
            context={"message": "api_key='sk-abc123def456ghi789jkl012mno345pqr678stu'"},
        )
    )

    assert decision.status == GovernanceDecisionStatus.ALLOW
    assert decision.risk_level == "low"
    assert decision.reason == "no CPE policy configured"
    assert decision.audit_payload["content_inspection"] is False
    assert decision.audit_payload["policy"] == "permissive-no-content-inspection"
    assert "sensitive_context" not in decision.audit_payload
```

- [ ] **Step 3: Run RED**

```bash
pytest tests/test_governance_skeleton.py::test_cpe_default_decision_contract_allows_without_runtime_policy tests/test_governance_skeleton.py::test_cpe_does_not_inspect_customer_message_content_by_default -q
```

Expected: FAIL because CPE still scans content and emits `sensitive_context`.

## Task 2: RED Routing Dry-Run No-Inspection Test

**Files:**

- Modify: `tests/test_cpe_routing_entrypoint.py`

- [ ] **Step 1: Replace routing approval test**

Rename `test_routing_cpe_dry_run_records_approval_required_for_sensitive_cloud` to:

```python
async def test_routing_cpe_dry_run_does_not_inspect_customer_message_content(monkeypatch):
```

Change assertions to:

```python
decision = calls["audit"]["decision"]
assert decision.status.value == "allow"
assert decision.risk_level == "low"
assert decision.audit_payload["content_inspection"] is False
assert "sensitive_context" not in decision.audit_payload
assert calls["audit"]["payload"] == {"surface": "routing", "mode": "dry_run"}
```

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_cpe_routing_entrypoint.py::test_routing_cpe_dry_run_does_not_inspect_customer_message_content -q
```

Expected: FAIL because CPE still returns `require_approval` for the sample content.

## Task 3: GREEN CPE Permissive Policy

**Files:**

- Modify: `src/agentmind/governance/cpe.py`

- [ ] **Step 1: Remove content scanning**

Replace `CPE` with a permissive boundary:

```python
from __future__ import annotations

from agentmind.governance.types import (
    CPERequest,
    GovernanceDecision,
    GovernanceDecisionStatus,
)


class CPE:
    """Context Policy Engine decision boundary.

    Phase 5 keeps this boundary permissive by default. Future policy packages
    can add explicit inspection rules without changing service callers.
    """

    def evaluate(self, request: CPERequest) -> GovernanceDecision:
        return GovernanceDecision(
            status=GovernanceDecisionStatus.ALLOW,
            reason="no CPE policy configured",
            risk_level="low",
            audit_payload=self._audit_payload(request),
        )

    def _audit_payload(self, request: CPERequest) -> dict:
        return {
            "component": "CPE",
            "trace_id": request.trace_id,
            "user_id": request.user_id,
            "agent_id": request.agent_id,
            "agent_security_level": request.agent_security_level,
            "memory_count": len(request.memory_items),
            "content_inspection": False,
            "policy": "permissive-no-content-inspection",
        }
```

- [ ] **Step 2: Run GREEN focused tests**

```bash
pytest tests/test_governance_skeleton.py::test_cpe_default_decision_contract_allows_without_runtime_policy tests/test_governance_skeleton.py::test_cpe_does_not_inspect_customer_message_content_by_default tests/test_cpe_routing_entrypoint.py::test_routing_cpe_dry_run_does_not_inspect_customer_message_content -q
```

Expected: PASS.

## Task 4: Update Phase 5 Readiness

**Files:**

- Modify: `docs/phase5/phase-5-readiness.md`

- [ ] **Step 1: Replace sensitive policy wording**

Document that Phase 5 currently preserves architecture only:

```markdown
Current CPE runtime policy is permissive and does not inspect customer message content. It records only governance metadata such as agent id, security level, memory count, policy name, and `content_inspection=false`.
```

- [ ] **Step 2: Run package verification**

```bash
pytest tests/test_governance_skeleton.py tests/test_cpe_routing_entrypoint.py tests/test_audit_service.py tests/test_phase5_readiness_audit.py -q
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
git add src/agentmind/governance/cpe.py tests/test_governance_skeleton.py tests/test_cpe_routing_entrypoint.py docs/phase5/phase-5-readiness.md docs/superpowers/plans/2026-05-27-phase-5-cpe-permissive-no-content-inspection.md
git commit -m "refactor: keep cpe permissive without content inspection"
```
