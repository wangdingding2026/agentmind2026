# Phase 3 Closure Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record and guard Phase 3 closure status before entering Phase 4 `ChannelHub` work.

**Architecture:** This package does not migrate runtime code. It creates a closure inventory that says which Phase 3 services are target architecture, which compatibility boundaries remain, and why Feishu lifecycle is deliberately deferred to Phase 4. Tests guard that the inventory exists, names required services, and keeps panel transition scope limited to Feishu lifecycle.

**Tech Stack:** Markdown architecture inventory, Python source/path audit tests, pytest.

---

## Scope

Target in this package:

- Add `docs/phase3/phase-3-closure-status.md`.
- Add `tests/test_phase3_closure_audit.py`.
- Assert required Phase 3 services exist:
  - `StrategyManager`
  - `ProtocolGateway`
  - `AgentCapabilityRegistry`
  - `OrchestrationEngine`
  - `AuditService`
  - control-plane services created during panel boundary work
- Assert the panel boundary document only lists Feishu lifecycle as transition handlers.
- Assert the closure document clearly directs Feishu connect/disconnect/status to Phase 4 `ChannelHub`.

Transition boundaries preserved:

- `feishu_connect`
- `feishu_disconnect`
- `feishu_status`

Out of scope:

- Do not migrate Feishu lifecycle in this package.
- Do not create `ChannelHub`.
- Do not change service behavior.
- Do not adjust existing endpoint behavior.

## Files

- Create: `docs/phase3/phase-3-closure-status.md`
  - Summarizes completed Phase 3 packages.
  - Records target architecture vs transition boundaries.
  - States Phase 4 entry recommendation.
- Create: `tests/test_phase3_closure_audit.py`
  - Guards the closure status document and required source files.
  - Guards panel transition handlers against expansion.

## Tasks

### Task 1: RED Closure Audit

- [ ] **Step 1: Write failing audit tests**

Add tests that require:

- `docs/phase3/phase-3-closure-status.md` exists;
- the document mentions required services and Phase 4 `ChannelHub`;
- all expected service files exist;
- `docs/phase3/panel-control-plane-boundary.md` documents only Feishu lifecycle transition handlers.

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_phase3_closure_audit.py -q
```

Expected: FAIL because `docs/phase3/phase-3-closure-status.md` does not exist.

### Task 2: GREEN Closure Status

- [ ] **Step 1: Add closure status document**

Create `docs/phase3/phase-3-closure-status.md` with:

- Phase 3 completed capability list;
- control-plane service boundary list;
- remaining transition boundary list;
- explicit recommendation to enter Phase 4 `ChannelHub` before Feishu lifecycle migration;
- note that session/stream runtime state still needs persistence/recovery after service boundary migration.

- [ ] **Step 2: Run focused GREEN**

```bash
pytest tests/test_phase3_closure_audit.py -q
```

Expected: PASS.

### Task 3: Verification

- [ ] **Step 1: Run architecture regression**

```bash
pytest tests/test_phase2_architecture_audit.py tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py -q
```

- [ ] **Step 2: Run panel regression**

```bash
pytest tests/test_panel_api.py -q
```

- [ ] **Step 3: Run router/panel regression**

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

- [ ] **Step 4: Run full regression**

```bash
pytest -q
```

### Task 4: Commit

- [ ] **Step 1: Check diff hygiene**

```bash
git diff --check
git status --short
```

- [ ] **Step 2: Review and commit**

```bash
git add docs/superpowers/plans/2026-05-27-phase-3-closure-audit.md docs/phase3/phase-3-closure-status.md tests/test_phase3_closure_audit.py
git commit -m "docs: record phase 3 closure status"
```

## Self-Review

- Spec coverage: Covers closure audit only.
- Placeholder scan: No TODO/TBD/fill-in markers.
- Architecture fit: Does not weaken old-path boundaries; it confirms Feishu lifecycle is intentionally deferred to Phase 4 instead of being patched into another panel service.
