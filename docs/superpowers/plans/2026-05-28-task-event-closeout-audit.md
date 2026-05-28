# Task Event Closeout Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the current observability/task-event route with an audit document and tests, without adding runtime behavior, UI, API/channel replay, stream replay, or governance enforcement.

**Architecture:** This package is documentation and architecture audit only. It records that task-event production, timeline query, explanation timeline, TaskReplayService, panel replay adapter, and partial-output capture are complete for this route. It keeps deferred work explicit: API/channel replay, observability UI, stream runtime replay, live SSE listener queue persistence/restoration, governance enforcement, customer-content inspection, and old fallback expansion.

**Tech Stack:** Python pytest architecture audit tests, Markdown closeout docs.

---

## File Structure

- Create: `tests/test_task_event_closeout_audit.py`
  - Requires `docs/observability/task-event-closeout-status.md`.
  - Verifies completed and deferred observability/task-event boundaries.
  - Verifies readiness docs point to the closeout status.
- Create: `docs/observability/task-event-closeout-status.md`
  - Documents the closeout decision and completed boundaries.
  - Documents compatibility/deferred boundaries and explicit non-goals.
- Modify: `docs/observability/task-event-readiness.md`
  - Updates Next Direction to point to `docs/observability/task-event-closeout-status.md`.
- Modify: `docs/observability/task-event-replay-readiness.md`
  - Updates Next Direction to point to `docs/observability/task-event-closeout-status.md`.
- Modify: `docs/observability/task-replay-adapter-readiness.md`
  - Updates Next Direction to point to closeout and future optional API/channel/UI packages.

No production code should change in this package.

### Task 1: Add Closeout RED Test

**Files:**
- Create: `tests/test_task_event_closeout_audit.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_task_event_closeout_audit.py`:

```python
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLOSEOUT_DOC = PROJECT_ROOT / "docs" / "observability" / "task-event-closeout-status.md"
TASK_EVENT_READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-readiness.md"
)
REPLAY_READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-replay-readiness.md"
)
ADAPTER_READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-replay-adapter-readiness.md"
)


REQUIRED_CLOSEOUT_MARKERS = {
    "observability/task-event route is closed",
    "TaskEventService owns stored task timeline events",
    "TaskService produces lifecycle task events",
    "TaskService produces `partial_output` task events",
    "TaskTimelineService owns read-side timeline DTO assembly",
    "TaskExplanationService includes timeline data through TaskTimelineService",
    "TaskReplayService owns the service-level replay DTO boundary",
    "panel `task_replay` handler calls TaskReplayService",
    "panel/API/channel remain adapters",
    "stream_snapshot remains in-process backlog only",
    "live SSE listener queues are not persisted or restored",
    "Replay uses persisted task timeline events",
    "does not reconstruct live SSE listener queues",
    "no API replay endpoint",
    "no channel replay adapter",
    "no observability UI",
    "no stream runtime replay",
    "no CPE or AgentShield enforcement",
    "no customer-content inspection",
    "no TaskEventService schema change",
    "no TaskTimelineService ordering or query change",
    "no SessionRuntimeService change",
    "no `feishu.route_callback` migration expansion",
}


def _closeout_text() -> str:
    assert CLOSEOUT_DOC.exists(), (
        "docs/observability/task-event-closeout-status.md is required"
    )
    return CLOSEOUT_DOC.read_text(encoding="utf-8")


def test_task_event_closeout_document_exists_and_declares_closed():
    text = _closeout_text()

    assert "observability/task-event route is closed" in text
    assert "closeout decision" in text


def test_task_event_closeout_document_names_required_boundaries():
    text = _closeout_text()
    missing = sorted(marker for marker in REQUIRED_CLOSEOUT_MARKERS if marker not in text)

    assert missing == []


def test_task_event_readiness_points_to_closeout_status():
    text = TASK_EVENT_READINESS_DOC.read_text(encoding="utf-8")

    assert "docs/observability/task-event-closeout-status.md" in text


def test_task_event_replay_readiness_points_to_closeout_status():
    text = REPLAY_READINESS_DOC.read_text(encoding="utf-8")

    assert "docs/observability/task-event-closeout-status.md" in text


def test_task_replay_adapter_readiness_points_to_closeout_status():
    text = ADAPTER_READINESS_DOC.read_text(encoding="utf-8")

    assert "docs/observability/task-event-closeout-status.md" in text
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_task_event_closeout_audit.py -q
```

Expected: FAIL because `docs/observability/task-event-closeout-status.md` does not exist and readiness docs do not point to it.

### Task 2: Add Closeout Document and Next Direction Updates

**Files:**
- Create: `docs/observability/task-event-closeout-status.md`
- Modify: `docs/observability/task-event-readiness.md`
- Modify: `docs/observability/task-event-replay-readiness.md`
- Modify: `docs/observability/task-replay-adapter-readiness.md`

- [ ] **Step 1: Create closeout status document**

Create `docs/observability/task-event-closeout-status.md`:

```markdown
# Task Event Closeout Status

## Closeout Decision

The observability/task-event route is closed.

This closeout decision covers persisted task-event production, task timeline query, task explanation timeline inclusion, service-level replay DTOs, the read-only panel replay adapter, and partial-output event capture.

No new runtime behavior is added in this closeout package.

## Completed Boundaries

TaskEventService owns stored task timeline events.

TaskService produces lifecycle task events for task start, routing start, agent selection, execution start, completion, and failure.

TaskService produces `partial_output` task events for streaming executor output.

TaskTimelineService owns read-side timeline DTO assembly over TaskEventService events.

TaskExplanationService includes timeline data through TaskTimelineService.

TaskReplayService owns the service-level replay DTO boundary over TaskTimelineService.

The panel `task_replay` handler calls TaskReplayService and returns the service DTO.

panel/API/channel remain adapters.

Replay uses persisted task timeline events.

Replay does not reconstruct live SSE listener queues.

## Runtime Boundary

stream_snapshot remains in-process backlog only.

live SSE listener queues are not persisted or restored.

Persistent replay is represented by stored task timeline events, not raw stream queue objects.

## Deferred Work

- no API replay endpoint;
- no channel replay adapter;
- no observability UI;
- no stream runtime replay;
- no live SSE listener queue persistence or restoration;
- no CPE or AgentShield enforcement;
- no customer-content inspection;
- no TaskEventService schema change;
- no TaskTimelineService ordering or query change;
- no SessionRuntimeService change;
- no `feishu.route_callback` migration expansion.

## Verification Gate

Task-event closeout is guarded by closeout audit tests, task-event readiness tests, replay readiness tests, adapter readiness tests, TaskEventService tests, TaskTimelineService tests, TaskReplayService tests, task producer tests, panel architecture tests, router/panel regression, and full pytest.

## Next Direction

The next package should be selected as a separate product decision:

- API replay endpoint;
- channel replay adapter;
- observability UI;
- Feishu `route_callback` fallback deletion readiness.

Each future package must keep services responsible for work and panel/API/channel as adapters.
```

- [ ] **Step 2: Update readiness next directions**

In `docs/observability/task-event-readiness.md`, replace the `## Next Direction` body with:

```markdown
The task-event service, producer, timeline, replay service, and panel replay adapter boundaries are closed in `docs/observability/task-event-closeout-status.md`.
```

In `docs/observability/task-event-replay-readiness.md`, replace the `## Next Direction` body with:

```markdown
After the service and panel adapter contracts remain green, this route is closed in `docs/observability/task-event-closeout-status.md`.

Future API replay, channel replay, observability UI, stream runtime replay, governance enforcement, and customer-content inspection require separate packages.
```

In `docs/observability/task-replay-adapter-readiness.md`, replace the `## Next Direction` body with:

```markdown
This adapter route is closed in `docs/observability/task-event-closeout-status.md`.

Future API replay endpoint, channel replay adapter, observability UI, stream runtime replay, governance enforcement, and customer-content inspection remain separate future decisions.
```

- [ ] **Step 3: Run GREEN focused test**

Run:

```bash
pytest tests/test_task_event_closeout_audit.py -q
```

Expected: PASS.

### Task 3: Run Required Regression Gates

**Files:**
- Read: all modified files

- [ ] **Step 1: Run focused observability closeout tests**

Run:

```bash
pytest tests/test_task_event_closeout_audit.py tests/test_observability_task_event_readiness.py tests/test_task_event_replay_readiness.py tests/test_task_replay_adapter_readiness.py -q
```

Expected: PASS.

- [ ] **Step 2: Run observability/service gate**

Run:

```bash
pytest tests/test_task_event_closeout_audit.py tests/test_task_service.py tests/test_task_event_service.py tests/test_task_timeline_service.py tests/test_task_replay_service.py tests/test_task_event_replay_readiness.py tests/test_observability_task_event_readiness.py tests/test_task_replay_adapter_readiness.py -q
```

Expected: PASS.

- [ ] **Step 3: Run panel/architecture gate**

Run:

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase5_closure_audit.py -q
```

Expected: PASS.

- [ ] **Step 4: Run router/panel regression**

Run:

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full verification**

Run:

```bash
pytest -q
git diff --check
git status --short
```

Expected: pytest PASS, diff check clean, status shows only intended changed files before commit.

- [ ] **Step 6: Commit**

Run:

```bash
git add tests/test_task_event_closeout_audit.py docs/observability/task-event-closeout-status.md docs/observability/task-event-readiness.md docs/observability/task-event-replay-readiness.md docs/observability/task-replay-adapter-readiness.md docs/superpowers/plans/2026-05-28-task-event-closeout-audit.md
git commit -m "docs: close task event observability route"
```

Expected: commit succeeds.

## Self-Review

- Spec coverage: the plan closes the current observability/task-event route and records completed/deferred work.
- Placeholder scan: no TBD/TODO/implement-later placeholders remain.
- Scope check: no production code, runtime replay, UI, API/channel replay, stream queue persistence, governance enforcement, customer-content inspection, schema/query/order changes, SessionRuntimeService changes, or `feishu.route_callback` expansion is included.
