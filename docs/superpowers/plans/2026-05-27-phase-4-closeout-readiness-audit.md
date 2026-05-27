# Phase 4 Closeout Readiness Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Phase 4 by documenting and testing the final ChannelHub, Feishu, panel runtime, and session runtime boundaries.

**Architecture:** This package is a closeout/readiness audit, not a new runtime migration. Phase 4 is considered closed only when a dedicated closure document records completed boundaries, remaining compatibility layers, explicit non-goals, verification suites, and the next phase entry criteria. Existing services stay as they are: `ChannelHub` owns channel lifecycle and Feishu message glue, `SessionRuntimeService` owns panel-facing active session/attach/stream boundaries, and panel/startup remain adapters.

**Tech Stack:** Python, pytest architecture audits, Markdown closure docs, existing `ChannelHub`, `SessionRuntimeService`, `FeishuAdapter`, startup and panel tests.

---

## Scope

Target in this package:

- Add a dedicated Phase 4 closure document:
  - `docs/phase4/phase-4-closure-status.md`
- Add architecture audit tests that require the closure doc to state:
  - Phase 4 is closed;
  - `ChannelHub` owns channel lifecycle/status;
  - Feishu inbound uses `ChannelMessage`;
  - Feishu discussion stop-word handling lives behind `ChannelHub`;
  - `feishu.route_callback` remains a migration fallback with delete-after criteria;
  - startup Feishu auto-start delegates to `ChannelHub`;
  - `SessionRuntimeService` owns active sessions, attach binding, stream events, and stream snapshot boundaries;
  - active discussion state and attach bindings have startup recovery;
  - live stream listener queues are volatile and are not restored;
  - persistent task-event replay is deferred to an observability/task-event package;
  - Phase 5 must not start until this closeout audit is green.
- Update existing Phase 3 boundary docs so their next direction points to Phase 5 readiness after Phase 4 closure, not to more Phase 4 migration.

Out of scope:

- Do not implement persistent task-event replay.
- Do not delete `feishu.route_callback`.
- Do not move API/Webhook channels.
- Do not change runtime behavior unless an audit exposes a concrete defect.
- Do not start Phase 5 CPE or AgentShield implementation.

## Files

- Create: `docs/phase4/phase-4-closure-status.md`
  - Dedicated Phase 4 closure status and next-step document.
- Create or modify: `tests/test_phase4_closure_audit.py`
  - Architecture tests for Phase 4 closure markers and required boundaries.
- Modify: `docs/phase3/phase-3-closure-status.md`
  - Point from Phase 3 context to the new Phase 4 closure doc and Phase 5 readiness.
- Modify: `docs/phase3/panel-control-plane-boundary.md`
  - Update next migration direction after Phase 4 closure.

## Tasks

### Task 1: RED Phase 4 Closure Document Exists

**Files:**
- Create: `tests/test_phase4_closure_audit.py`

- [ ] **Step 1: Add failing closure document test**

Create `tests/test_phase4_closure_audit.py` with:

```python
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE4_DOC = PROJECT_ROOT / "docs" / "phase4" / "phase-4-closure-status.md"
PHASE3_DOC = PROJECT_ROOT / "docs" / "phase3" / "phase-3-closure-status.md"
PANEL_BOUNDARY_DOC = PROJECT_ROOT / "docs" / "phase3" / "panel-control-plane-boundary.md"


def _phase4_text() -> str:
    assert PHASE4_DOC.exists(), "docs/phase4/phase-4-closure-status.md is required"
    return PHASE4_DOC.read_text(encoding="utf-8")


def test_phase4_closure_document_exists_and_declares_closed():
    text = _phase4_text()

    assert "Phase 4 is closed" in text
    assert "ChannelHub" in text
    assert "SessionRuntimeService" in text
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_phase4_closure_audit.py::test_phase4_closure_document_exists_and_declares_closed -q
```

Expected: FAIL because the Phase 4 closure document does not exist yet.

### Task 2: RED Required Phase 4 Boundaries

**Files:**
- Modify: `tests/test_phase4_closure_audit.py`

- [ ] **Step 1: Add required marker audit**

Append:

```python
REQUIRED_PHASE4_MARKERS = {
    "Phase 4 is closed",
    "ChannelHub",
    "channel lifecycle",
    "channel status",
    "startup Feishu auto-start",
    "ChannelMessage",
    "Feishu inbound",
    "discussion stop-word",
    "feishu.route_callback",
    "migration fallback",
    "delete after",
    "SessionRuntimeService",
    "active_sessions",
    "attach_to_task",
    "panel_task_stream",
    "stream_snapshot",
    "active discussion state",
    "attach bindings",
    "startup recovery",
    "live stream listener queues remain volatile",
    "persistent task-event replay",
    "observability/task-event",
    "Phase 5 readiness",
}


def test_phase4_closure_document_names_required_boundaries():
    text = _phase4_text()
    missing = sorted(marker for marker in REQUIRED_PHASE4_MARKERS if marker not in text)

    assert missing == []
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_phase4_closure_audit.py::test_phase4_closure_document_names_required_boundaries -q
```

Expected: FAIL until the closure document includes all required boundaries.

### Task 3: RED Phase 3 Docs Point To Phase 4 Closure

**Files:**
- Modify: `tests/test_phase4_closure_audit.py`

- [ ] **Step 1: Add cross-doc audit**

Append:

```python
def test_phase3_docs_reference_phase4_closure_and_phase5_readiness():
    docs = "\n".join([
        PHASE3_DOC.read_text(encoding="utf-8"),
        PANEL_BOUNDARY_DOC.read_text(encoding="utf-8"),
    ])

    assert "docs/phase4/phase-4-closure-status.md" in docs
    assert "Phase 5 readiness" in docs
    assert "Phase 4 closeout/readiness audit" not in docs
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_phase4_closure_audit.py::test_phase3_docs_reference_phase4_closure_and_phase5_readiness -q
```

Expected: FAIL because the Phase 3 docs still point at the closeout audit instead of a completed closure artifact.

### Task 4: GREEN Closure Docs

**Files:**
- Create: `docs/phase4/phase-4-closure-status.md`
- Modify: `docs/phase3/phase-3-closure-status.md`
- Modify: `docs/phase3/panel-control-plane-boundary.md`

- [ ] **Step 1: Create Phase 4 closure doc**

Create `docs/phase4/phase-4-closure-status.md` with sections:

```markdown
# Phase 4 Closure Status

## Closure Decision

Phase 4 is closed for control-panel runtime and channel boundary work.

## Completed Boundaries

- `ChannelHub` owns channel lifecycle and channel status.
- Panel Feishu handlers delegate `feishu_connect`, `feishu_disconnect`, and `feishu_status` to `ChannelHub`.
- Startup Feishu auto-start delegates to `ChannelHub`.
- Feishu inbound messages convert to `ChannelMessage` before business dispatch.
- Feishu discussion stop-word handling lives behind the `ChannelHub` standard message boundary.
- `SessionRuntimeService` owns `active_sessions`, `attach_to_task`, `panel_task_stream`, and `stream_snapshot`.
- Active discussion state and attach bindings have startup recovery through `SessionRuntimeService`.

## Compatibility Boundaries

- `feishu.route_callback` remains a migration fallback only. Delete after Feishu inbound handling no longer needs `route_callback` fallback and all supported Feishu inbound paths use `ChannelMessage`.
- Live stream listener queues remain volatile and are not restored. `stream_snapshot` exposes only in-process backlog snapshots.

## Explicit Non-Goals

- Persistent task-event replay is deferred to a later observability/task-event package.
- Phase 5 readiness does not require deleting `feishu.route_callback`; it requires keeping it bounded and documented.
- Phase 5 CPE and AgentShield work is not part of Phase 4.

## Verification Gate

Phase 4 closure is guarded by ChannelHub, Feishu adapter, startup, panel boundary, session runtime, stream, router/panel, and full pytest suites.

## Next Direction

Start Phase 5 readiness only after this closure audit remains green.
```

- [ ] **Step 2: Update Phase 3 docs**

In `docs/phase3/phase-3-closure-status.md`, replace the final next-step sentence with:

```text
Phase 4 closure is recorded in `docs/phase4/phase-4-closure-status.md`. Next, run Phase 5 readiness before starting CPE or AgentShield work.
```

In `docs/phase3/panel-control-plane-boundary.md`, replace the current next migration direction list with:

```text
1. Phase 5 readiness, using `docs/phase4/phase-4-closure-status.md` as the Phase 4 closure source.
2. Decide whether persistent task-event replay belongs in a later observability/task-event package rather than Phase 4 live stream runtime.
```

- [ ] **Step 3: Run GREEN focused audit tests**

Run:

```bash
pytest tests/test_phase4_closure_audit.py -q
```

Expected: all tests pass.

### Task 5: Regression And Verification

**Files:**
- Existing test suites.

- [ ] **Step 1: Phase 4 focused boundary tests**

Run:

```bash
pytest tests/test_phase4_closure_audit.py tests/test_channel_hub.py tests/test_session_runtime_service.py tests/test_stream.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Feishu/channel regression**

Run:

```bash
pytest tests/test_startup.py tests/test_channel_hub.py tests/test_feishu_channel.py tests/test_feishu_path.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Panel/architecture regression**

Run:

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py tests/test_phase4_closure_audit.py -q
```

Expected: all selected tests pass.

- [ ] **Step 4: Router/panel regression**

Run:

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Full verification**

Run:

```bash
pytest -q
git diff --check
git status --short
```

Expected: full pytest passes, whitespace check is clean, and git status only shows this package's intended files before commit.

### Task 6: Commit

**Files:**
- Stage only files changed by this package.

- [ ] **Step 1: Review diff**

Run:

```bash
git diff -- docs/phase4/phase-4-closure-status.md docs/phase3/phase-3-closure-status.md docs/phase3/panel-control-plane-boundary.md tests/test_phase4_closure_audit.py docs/superpowers/plans/2026-05-27-phase-4-closeout-readiness-audit.md
```

- [ ] **Step 2: Commit**

Run:

```bash
git add docs/phase4/phase-4-closure-status.md docs/phase3/phase-3-closure-status.md docs/phase3/panel-control-plane-boundary.md tests/test_phase4_closure_audit.py docs/superpowers/plans/2026-05-27-phase-4-closeout-readiness-audit.md
git commit -m "docs: close phase 4 runtime boundaries"
```

## Self-Review

- Spec coverage: closes Phase 4 without adding Phase 5 implementation.
- Placeholder scan: no deferred placeholders or ambiguous TODOs.
- Type/name consistency: uses existing `ChannelHub`, `ChannelMessage`, `SessionRuntimeService`, `stream_snapshot`, panel handler names, and Feishu callback names.
