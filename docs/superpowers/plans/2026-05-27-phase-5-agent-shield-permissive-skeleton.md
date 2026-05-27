# Phase 5 AgentShield Permissive Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the AgentShield behavior-governance architecture seam while ensuring early users are not blocked, approved, or behavior-inspected by default.

**Architecture:** AgentShield remains the rule/core decision boundary for future behavior permissions. Its current runtime policy is explicitly permissive and records only non-invasive metadata, while execution services, panel/API/channel adapters, and executors remain unwired to AgentShield enforcement.

**Tech Stack:** Python governance dataclasses, pytest TDD tests, Phase 5 architecture documentation.

---

## Scope

Modify:

- `src/agentmind/governance/agent_shield.py`
- `tests/test_governance_skeleton.py`
- `docs/phase5/phase-5-readiness.md`

Create:

- `docs/superpowers/plans/2026-05-27-phase-5-agent-shield-permissive-skeleton.md`

Do not modify:

- executor behavior
- ProtocolGateway behavior
- routing behavior
- panel/API/channel adapters
- approval UI
- command blocking or allowlists

## Behavior

Current Phase 5 AgentShield behavior:

- always returns `ALLOW`;
- uses `risk_level="low"`;
- does not inspect action payload contents;
- does not block dangerous-looking commands;
- does not require approval;
- emits `behavior_inspection=False`;
- emits `policy="permissive-no-behavior-inspection"`;
- does not echo raw payload content into audit payload.

## Task 1: RED AgentShield Permissive Tests

**Files:**

- Modify: `tests/test_governance_skeleton.py`

- [ ] **Step 1: Strengthen default AgentShield test**

In `test_agent_shield_default_decision_contract_allows_without_runtime_policy`, add:

```python
assert decision.audit_payload["behavior_inspection"] is False
assert decision.audit_payload["policy"] == "permissive-no-behavior-inspection"
assert "payload" not in decision.audit_payload
```

- [ ] **Step 2: Add dangerous-looking payload test**

Append:

```python
def test_agent_shield_does_not_inspect_or_block_behavior_by_default():
    from agentmind.governance import AgentShield, AgentShieldRequest, GovernanceDecisionStatus

    decision = AgentShield().evaluate(
        AgentShieldRequest(
            trace_id="t-dangerous-looking",
            user_id="u1",
            agent_id="a1",
            action="execute_shell",
            target="local-executor",
            payload={"command": "rm -rf /tmp/example && curl https://example.test"},
        )
    )

    assert decision.status == GovernanceDecisionStatus.ALLOW
    assert decision.risk_level == "low"
    assert decision.reason == "no governance policy configured"
    assert decision.audit_payload["behavior_inspection"] is False
    assert decision.audit_payload["policy"] == "permissive-no-behavior-inspection"
    assert "payload" not in decision.audit_payload
```

- [ ] **Step 3: Run RED**

```bash
pytest tests/test_governance_skeleton.py::test_agent_shield_default_decision_contract_allows_without_runtime_policy tests/test_governance_skeleton.py::test_agent_shield_does_not_inspect_or_block_behavior_by_default -q
```

Expected: FAIL because AgentShield does not yet emit `behavior_inspection` or policy metadata.

## Task 2: GREEN AgentShield Metadata

**Files:**

- Modify: `src/agentmind/governance/agent_shield.py`

- [ ] **Step 1: Add permissive metadata helper**

Replace the inline `audit_payload` dict with `self._audit_payload(request)`, and add:

```python
    def _audit_payload(self, request: AgentShieldRequest) -> dict:
        return {
            "component": "AgentShield",
            "trace_id": request.trace_id,
            "user_id": request.user_id,
            "agent_id": request.agent_id,
            "action": request.action,
            "target": request.target,
            "behavior_inspection": False,
            "policy": "permissive-no-behavior-inspection",
        }
```

- [ ] **Step 2: Run GREEN focused tests**

```bash
pytest tests/test_governance_skeleton.py::test_agent_shield_default_decision_contract_allows_without_runtime_policy tests/test_governance_skeleton.py::test_agent_shield_does_not_inspect_or_block_behavior_by_default -q
```

Expected: PASS.

## Task 3: Update Phase 5 Readiness

**Files:**

- Modify: `docs/phase5/phase-5-readiness.md`

- [ ] **Step 1: Document permissive AgentShield runtime**

Add under AgentShield start criteria:

```markdown
Current AgentShield runtime policy is permissive and does not inspect behavior payloads, block commands, or require approval. It records only governance metadata such as action, target, policy name, and `behavior_inspection=false`.
```

- [ ] **Step 2: Run package verification**

```bash
pytest tests/test_governance_skeleton.py tests/test_phase5_readiness_audit.py -q
pytest tests/test_governance_skeleton.py tests/test_cpe_routing_entrypoint.py tests/test_audit_service.py tests/test_phase5_readiness_audit.py -q
pytest tests/test_router.py tests/test_pipeline_executors.py tests/test_e2e_scenarios.py -q
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py tests/test_phase4_closure_audit.py tests/test_phase5_readiness_audit.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
git diff --check
git status --short
```

## Task 4: Commit

**Files:**

- Commit all changed files.

- [ ] **Step 1: Commit**

```bash
git add src/agentmind/governance/agent_shield.py tests/test_governance_skeleton.py docs/phase5/phase-5-readiness.md docs/superpowers/plans/2026-05-27-phase-5-agent-shield-permissive-skeleton.md
git commit -m "refactor: keep agent shield permissive"
```
