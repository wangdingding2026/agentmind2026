# Phase 3 Panel Boundary Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guard the Phase 3 panel control-plane boundary so migrated endpoints stay service-backed while remaining runtime/channel endpoints are explicitly classified as transition work.

**Architecture:** The target architecture is still: panel adapts HTTP requests, service layer does the work, rule/core layers own rules and decisions. This package does not move Feishu runtime lifecycle or session streaming into services yet; it documents those as Phase 4/deferred boundaries and adds architecture tests so temporary direct logic cannot quietly expand into a new long-term dependency.

**Tech Stack:** FastAPI panel router, Python AST/source scanning tests, pytest, Markdown architecture inventory.

---

## Scope

Target boundary:

- Panel endpoints that manage tasks, agents, rules, settings saves, audit events, routing explanations, and control overview must delegate to services.
- Panel must not rebuild agent DTOs, mutate executor registries, write route/rule files directly, or assemble settings write sections for already migrated paths.
- Services remain allowed to compose lower-level config, registry, task, audit, and rule/core objects.

Transition boundary:

- Feishu connect/disconnect/status remains direct in `panel/server.py` for now because it owns channel runtime lifecycle and should be migrated with Phase 4 `ChannelHub`.
- Active sessions, task attach, and task stream remain direct runtime state adapters until session/stream runtime state has a service boundary.
- Settings GET and embedding status are read-only control views and are acceptable until a read-side settings/status service package is scheduled.

Out of scope:

- Do not migrate Feishu connect/disconnect in this package.
- Do not introduce new long-term panel helpers for legacy paths.
- Do not change router behavior or ChannelHub.

## Files

- Create: `docs/phase3/panel-control-plane-boundary.md`
  - Records service-backed endpoints, transition endpoints, and forbidden direct patterns.
- Create: `tests/test_panel_control_plane_boundary.py`
  - Scans `src/agentmind/panel/server.py` and the boundary inventory.
  - Protects already migrated endpoints from direct registry/config/rule/storage logic.
  - Confirms remaining direct runtime patterns only appear in documented transition handlers.

## Tasks

### Task 1: RED Boundary Guard

- [ ] **Step 1: Write failing test**

Create `tests/test_panel_control_plane_boundary.py` with tests that:

- require `docs/phase3/panel-control-plane-boundary.md`;
- require the transition handler set to include Feishu lifecycle, sessions, attach, stream, settings GET, and embedding status;
- scan migrated handler bodies and reject direct runtime/config/rule/storage patterns.

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_panel_control_plane_boundary.py -q
```

Expected: FAIL because the boundary inventory document does not exist yet.

### Task 2: GREEN Boundary Inventory

- [ ] **Step 1: Add boundary inventory**

Create `docs/phase3/panel-control-plane-boundary.md` with:

- target architecture statement;
- service-backed endpoint list;
- transition endpoint list;
- forbidden patterns for service-backed handlers;
- next migration direction.

- [ ] **Step 2: Run GREEN focused tests**

Run:

```bash
pytest tests/test_panel_control_plane_boundary.py -q
```

Expected: PASS.

### Task 3: Verification

- [ ] **Step 1: Run panel regression**

```bash
pytest tests/test_panel_api.py -q
```

- [ ] **Step 2: Run architecture regression**

```bash
pytest tests/test_phase2_architecture_audit.py tests/test_panel_control_plane_boundary.py -q
```

- [ ] **Step 3: Run router/panel regression**

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

- [ ] **Step 4: Run full regression**

```bash
pytest -q
```

- [ ] **Step 5: Check diff hygiene**

```bash
git diff --check
git status --short
```

### Task 4: Commit

- [ ] **Step 1: Review diff**

```bash
git diff -- docs/superpowers/plans/2026-05-27-phase-3-panel-boundary-audit.md docs/phase3/panel-control-plane-boundary.md tests/test_panel_control_plane_boundary.py
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-05-27-phase-3-panel-boundary-audit.md docs/phase3/panel-control-plane-boundary.md tests/test_panel_control_plane_boundary.py
git commit -m "test: guard panel control plane boundaries"
```

## Self-Review

- Spec coverage: Covers this audit package only; it protects already migrated panel service boundaries and classifies deferred runtime paths.
- Placeholder scan: No TODO/TBD/fill-in markers.
- Architecture fit: The tests protect the user-confirmed rule that panel/API are adapters, services do the work, and rules/core remain decision/rule owners.
