# Observability UI Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an observability UI readiness gate for a future panel task replay/timeline view without implementing UI, changing APIs, or touching runtime behavior.

**Architecture:** This package is documentation and architecture audit only. It records that a future observability UI must consume the existing panel replay adapter backed by `TaskReplayService`, render service DTOs, and avoid assembling timelines or querying storage. It keeps API replay, channel UX expansion, stream runtime replay, queue restoration, governance enforcement, and customer-content inspection out of scope.

**Tech Stack:** Python pytest architecture audit tests, Markdown readiness docs.

---

## File Structure

- Create: `tests/test_observability_ui_readiness.py`
  - Requires `docs/observability/observability-ui-readiness.md`.
  - Verifies the future panel UI boundary, UX constraints, and non-goals.
  - Verifies task-event closeout and architecture final closeout point to the readiness gate.
- Create: `docs/observability/observability-ui-readiness.md`
  - Documents the future UI scope and adapter/service boundary.
- Modify: `docs/observability/task-event-closeout-status.md`
  - Updates Next Direction to point observability UI to the readiness gate.
- Modify: `docs/architecture/final-closeout-status.md`
  - Updates Future Work to point observability UI to the readiness gate.

No production code should change in this package.

### Task 1: Add Observability UI RED Test

**Files:**
- Create: `tests/test_observability_ui_readiness.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_observability_ui_readiness.py`:

```python
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "observability-ui-readiness.md"
)
FINAL_CLOSEOUT_DOC = PROJECT_ROOT / "docs" / "architecture" / "final-closeout-status.md"
TASK_EVENT_CLOSEOUT_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-closeout-status.md"
)


REQUIRED_OBSERVABILITY_UI_READINESS_MARKERS = {
    "observability UI readiness",
    "future panel observability UI",
    "task replay timeline view",
    "must consume the existing panel replay endpoint",
    "`/panel/api/tasks/{trace_id}/replay`",
    "TaskReplayService",
    "must render the service DTO",
    "must not assemble timeline",
    "must not query TaskEventService",
    "must not call TaskTimelineService directly",
    "must not connect to stream queues",
    "must not reconstruct live SSE listener queues",
    "must not implement stream runtime replay",
    "must not create an API replay endpoint",
    "must not expand channel replay UX",
    "must not enable CPE or AgentShield enforcement",
    "must not inspect customer content",
    "read-only",
    "found and missing states",
    "bounded event display",
    "partial_output events may be displayed",
    "implementation requires a separate small package",
}


def _readiness_text() -> str:
    assert READINESS_DOC.exists(), (
        "docs/observability/observability-ui-readiness.md is required"
    )
    return READINESS_DOC.read_text(encoding="utf-8")


def test_observability_ui_readiness_document_exists_and_defers_ui():
    text = _readiness_text()

    assert "observability UI readiness" in text
    assert "implementation requires a separate small package" in text


def test_observability_ui_readiness_names_required_boundaries():
    text = _readiness_text()
    missing = sorted(
        marker
        for marker in REQUIRED_OBSERVABILITY_UI_READINESS_MARKERS
        if marker not in text
    )

    assert missing == []


def test_final_closeout_points_to_observability_ui_readiness():
    text = FINAL_CLOSEOUT_DOC.read_text(encoding="utf-8")

    assert "docs/observability/observability-ui-readiness.md" in text


def test_task_event_closeout_points_to_observability_ui_readiness():
    text = TASK_EVENT_CLOSEOUT_DOC.read_text(encoding="utf-8")

    assert "docs/observability/observability-ui-readiness.md" in text
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_observability_ui_readiness.py -q
```

Expected: FAIL because `docs/observability/observability-ui-readiness.md` does not exist and closeout docs do not point to it.

### Task 2: Add Readiness Document and Closeout References

**Files:**
- Create: `docs/observability/observability-ui-readiness.md`
- Modify: `docs/observability/task-event-closeout-status.md`
- Modify: `docs/architecture/final-closeout-status.md`

- [ ] **Step 1: Create readiness document**

Create `docs/observability/observability-ui-readiness.md`:

```markdown
# Observability UI Readiness

## Readiness Decision

This document defines observability UI readiness.

A future panel observability UI can expose a task replay timeline view for task debugging, failure inspection, and partial output review.

The UI implementation requires a separate small package.

## UI Boundary

The future panel observability UI must consume the existing panel replay endpoint `/panel/api/tasks/{trace_id}/replay`.

The panel replay endpoint is backed by TaskReplayService.

The UI must render the service DTO returned by the panel replay endpoint.

The UI must be read-only.

The UI must support found and missing states.

The UI should use bounded event display.

partial_output events may be displayed from the replay DTO.

## Architecture Constraints

The UI must not assemble timeline data.

The UI must not query TaskEventService.

The UI must not call TaskTimelineService directly.

The UI must not connect to stream queues.

The UI must not reconstruct live SSE listener queues.

The UI must not implement stream runtime replay.

The UI must not create an API replay endpoint.

The UI must not expand channel replay UX.

The UI must not enable CPE or AgentShield enforcement.

The UI must not inspect customer content.

## Explicit Non-Goals

- no UI implementation in this package;
- no API replay endpoint;
- no channel replay UX expansion;
- no stream runtime replay;
- no live SSE listener queue persistence or restoration;
- no CPE or AgentShield enforcement;
- no customer-content inspection;
- no TaskEventService schema change;
- no TaskTimelineService ordering or query change;
- no SessionRuntimeService change.

## Verification Gate

Observability UI readiness is guarded by readiness audit tests, task-event closeout tests, architecture final closeout tests, panel architecture tests, router/panel regression, and full pytest.

## Next Direction

If selected for implementation, start a separate panel observability UI V1 package that renders the existing replay DTO from `/panel/api/tasks/{trace_id}/replay`.
```

- [ ] **Step 2: Update closeout references**

In `docs/observability/task-event-closeout-status.md`, add under `## Next Direction`:

```markdown
Observability UI readiness is tracked in `docs/observability/observability-ui-readiness.md`.
```

In `docs/architecture/final-closeout-status.md`, add near the existing readiness links:

```markdown
Observability UI readiness is tracked in `docs/observability/observability-ui-readiness.md`.
```

and change the future-work bullet from:

```markdown
- observability UI;
```

to:

```markdown
- observability UI, after `docs/observability/observability-ui-readiness.md`;
```

- [ ] **Step 3: Run GREEN**

Run:

```bash
pytest tests/test_observability_ui_readiness.py -q
```

Expected: PASS.

### Task 3: Regression Verification and Commit

**Files:**
- Test only.

- [ ] **Step 1: Run focused readiness suites**

Run:

```bash
pytest tests/test_observability_ui_readiness.py tests/test_task_event_closeout_audit.py tests/test_architecture_final_closeout_audit.py -q
```

Expected: PASS.

- [ ] **Step 2: Run observability/service regression**

Run:

```bash
pytest tests/test_observability_ui_readiness.py tests/test_task_replay_service.py tests/test_task_timeline_service.py tests/test_task_event_service.py tests/test_channel_replay_service.py -q
```

Expected: PASS.

- [ ] **Step 3: Run panel/architecture regression**

Run:

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase5_closure_audit.py tests/test_architecture_final_closeout_audit.py tests/test_observability_ui_readiness.py -q
```

Expected: PASS.

- [ ] **Step 4: Run router/panel regression**

Run:

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full validation**

Run:

```bash
pytest -q
git diff --check
git status --short
```

Expected: full pytest PASS, whitespace check clean, and only intended files changed before commit.

- [ ] **Step 6: Commit**

Run:

```bash
git add tests/test_observability_ui_readiness.py docs/observability/observability-ui-readiness.md docs/observability/task-event-closeout-status.md docs/architecture/final-closeout-status.md docs/superpowers/plans/2026-05-28-observability-ui-readiness.md
git commit -m "docs: add observability ui readiness"
```

Expected: commit succeeds.

## Self-Review

- Spec coverage: this plan covers observability UI readiness, existing panel replay adapter consumption, UI boundaries, explicit non-goals, verification, and commit.
- Placeholder scan: no TBD, TODO, or open implementation placeholders.
- Scope check: no UI implementation, API replay endpoint, channel replay UX expansion, stream runtime replay, live SSE queue persistence, governance enforcement, customer-content inspection, TaskEventService schema change, TaskTimelineService ordering/query change, or SessionRuntimeService change is included.
