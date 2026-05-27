# Phase 5 CPE Policy V1 Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give CPE its first real policy decision: sensitive context sent to a non-local agent requires approval, while routing still remains dry-run only.

**Architecture:** CPE owns information-flow policy in `agentmind.governance`. RoutingService already records CPE decisions as dry-run audit events and deliberately ignores them for behavior. This package changes only the CPE decision result for sensitive context; it does not block, reroute, or alter routing/memory behavior.

**Tech Stack:** Python regex policy helper, governance dataclasses/enums, pytest unit tests, existing routing regression tests.

---

## Scope

Modify:

- `src/agentmind/governance/cpe.py`
- `tests/test_governance_skeleton.py`
- `docs/phase5/phase-5-readiness.md`

Create:

- `docs/superpowers/plans/2026-05-27-phase-5-cpe-policy-v1-skeleton.md`

Do not modify RoutingService, RoutingPipeline, SensitiveScanner, CandidatePool, memory retrieval, panel, channels, or executors.

## Behavior

CPE v1 returns:

- `ALLOW` for non-sensitive context.
- `ALLOW` for sensitive context routed to `local`.
- `REQUIRE_APPROVAL` for sensitive context routed to `cloud` or `third_party`.

Sensitive context is detected from `CPERequest.context["message"]` using the existing API key/password pattern semantics.

The decision includes:

- `risk_level="high"` for approval-required decisions.
- `reason="sensitive context requires approval for non-local agent"`.
- audit payload keys: `component`, `trace_id`, `user_id`, `agent_id`, `agent_security_level`, `memory_count`, `sensitive_context`, `policy`.

## Non-Goals

- Do not enforce the approval result in routing.
- Do not block cloud or third-party agents.
- Do not change CandidatePool or SensitiveScanner.
- Do not gate memory retrieval.
- Do not add UI approval.
- Do not alter AuditService event shape.

## Task 1: RED CPE Policy Tests

**Files:**
- Modify: `tests/test_governance_skeleton.py`

- [ ] **Step 1: Add policy tests**

Append to `tests/test_governance_skeleton.py`:

```python
def test_cpe_requires_approval_for_sensitive_context_to_cloud_agent():
    from agentmind.governance import CPE, CPERequest, GovernanceDecisionStatus

    decision = CPE().evaluate(
        CPERequest(
            trace_id="t-sensitive",
            user_id="u1",
            agent_id="cloud_agent",
            agent_security_level="cloud",
            context={"message": "api_key='sk-abc123def456ghi789jkl012mno345pqr678stu'"},
        )
    )

    assert decision.status == GovernanceDecisionStatus.REQUIRE_APPROVAL
    assert decision.risk_level == "high"
    assert decision.reason == "sensitive context requires approval for non-local agent"
    assert decision.audit_payload["sensitive_context"] is True
    assert decision.audit_payload["policy"] == "sensitive-context-non-local-agent"


def test_cpe_allows_sensitive_context_to_local_agent():
    from agentmind.governance import CPE, CPERequest, GovernanceDecisionStatus

    decision = CPE().evaluate(
        CPERequest(
            trace_id="t-local",
            user_id="u1",
            agent_id="local_agent",
            agent_security_level="local",
            context={"message": 'password = "secret"'},
        )
    )

    assert decision.status == GovernanceDecisionStatus.ALLOW
    assert decision.risk_level == "low"
    assert decision.audit_payload["sensitive_context"] is True
```

- [ ] **Step 2: Update default allow test**

In `test_cpe_default_decision_contract_allows_without_runtime_policy`, update the expected reason to:

```python
assert decision.reason == "no CPE policy matched"
assert decision.audit_payload["sensitive_context"] is False
```

- [ ] **Step 3: Run RED**

```bash
pytest tests/test_governance_skeleton.py::test_cpe_requires_approval_for_sensitive_context_to_cloud_agent tests/test_governance_skeleton.py::test_cpe_allows_sensitive_context_to_local_agent tests/test_governance_skeleton.py::test_cpe_default_decision_contract_allows_without_runtime_policy -q
```

Expected: FAIL because CPE still always returns `ALLOW` with reason `no governance policy configured`.

## Task 2: GREEN CPE Policy V1

**Files:**
- Modify: `src/agentmind/governance/cpe.py`

- [ ] **Step 1: Add sensitive context detection and decision helpers**

Replace the file with:

```python
from __future__ import annotations

import re

from agentmind.governance.types import (
    CPERequest,
    GovernanceDecision,
    GovernanceDecisionStatus,
)


_SENSITIVE_RE = re.compile(
    r'(sk-[a-zA-Z0-9]{20,}|api_key\s*=\s*[\"\'][^\"\']+|password\s*=\s*[\"\'][^\"\']+)',
    re.IGNORECASE,
)


class CPE:
    """Context Policy Engine decision boundary."""

    def evaluate(self, request: CPERequest) -> GovernanceDecision:
        sensitive_context = self._has_sensitive_context(request)
        if sensitive_context and request.agent_security_level in {"cloud", "third_party"}:
            return GovernanceDecision(
                status=GovernanceDecisionStatus.REQUIRE_APPROVAL,
                reason="sensitive context requires approval for non-local agent",
                risk_level="high",
                audit_payload=self._audit_payload(
                    request,
                    sensitive_context=sensitive_context,
                    policy="sensitive-context-non-local-agent",
                ),
            )
        return GovernanceDecision(
            status=GovernanceDecisionStatus.ALLOW,
            reason="no CPE policy matched",
            risk_level="low",
            audit_payload=self._audit_payload(
                request,
                sensitive_context=sensitive_context,
                policy="default-allow",
            ),
        )

    def _has_sensitive_context(self, request: CPERequest) -> bool:
        message = str(request.context.get("message", ""))
        return bool(_SENSITIVE_RE.search(message))

    def _audit_payload(
        self,
        request: CPERequest,
        *,
        sensitive_context: bool,
        policy: str,
    ) -> dict:
        return {
            "component": "CPE",
            "trace_id": request.trace_id,
            "user_id": request.user_id,
            "agent_id": request.agent_id,
            "agent_security_level": request.agent_security_level,
            "memory_count": len(request.memory_items),
            "sensitive_context": sensitive_context,
            "policy": policy,
        }
```

- [ ] **Step 2: Run GREEN focused tests**

```bash
pytest tests/test_governance_skeleton.py::test_cpe_requires_approval_for_sensitive_context_to_cloud_agent tests/test_governance_skeleton.py::test_cpe_allows_sensitive_context_to_local_agent tests/test_governance_skeleton.py::test_cpe_default_decision_contract_allows_without_runtime_policy -q
```

Expected: PASS.

## Task 3: Update Phase 5 Readiness

**Files:**
- Modify: `docs/phase5/phase-5-readiness.md`

- [ ] **Step 1: Document CPE policy v1**

Add:

```markdown
CPE policy v1 marks sensitive context routed to non-local agents as `require_approval`, but RoutingService still records this as dry-run audit only and does not enforce it.
```

- [ ] **Step 2: Run focused tests**

```bash
pytest tests/test_governance_skeleton.py tests/test_cpe_routing_entrypoint.py tests/test_phase5_readiness_audit.py -q
```

Expected: PASS.

## Task 4: Regression Verification

**Files:**
- Test only.

- [ ] **Step 1: Run focused governance tests**

```bash
pytest tests/test_governance_skeleton.py tests/test_cpe_routing_entrypoint.py tests/test_audit_service.py tests/test_phase5_readiness_audit.py -q
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

## Task 5: Commit

**Files:**
- `docs/superpowers/plans/2026-05-27-phase-5-cpe-policy-v1-skeleton.md`
- `docs/phase5/phase-5-readiness.md`
- `src/agentmind/governance/cpe.py`
- `tests/test_governance_skeleton.py`

- [ ] **Step 1: Commit**

```bash
git add docs/superpowers/plans/2026-05-27-phase-5-cpe-policy-v1-skeleton.md docs/phase5/phase-5-readiness.md src/agentmind/governance/cpe.py tests/test_governance_skeleton.py
git commit -m "feat: add cpe policy v1 skeleton"
```

## Self-Review

- Spec coverage: Covers only CPE v1 decision behavior.
- Placeholder scan: No placeholders.
- Type consistency: Uses existing `GovernanceDecisionStatus.REQUIRE_APPROVAL`.
