# Task Replay Adapter Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only TaskReplay adapter readiness gate without implementing any panel, API, channel, stream runtime, or UI replay behavior.

**Architecture:** TaskReplayService already owns the service-level replay DTO boundary over TaskTimelineService. This package only documents and tests the future adapter entry conditions: adapters may call TaskReplayService and pass through its DTO, but must not assemble timelines, query TaskEventService, touch stream queues, add UI behavior, inspect customer content, or enable CPE/AgentShield enforcement.

**Tech Stack:** Python, pytest, Markdown architecture readiness docs.

---

## File Structure

- Create: `tests/test_task_replay_adapter_readiness.py`
  - Guards the existence and content of the adapter readiness document.
  - Guards that task-event replay readiness points to the adapter readiness gate.
- Create: `docs/observability/task-replay-adapter-readiness.md`
  - Defines read-only adapter readiness for future panel/API adapter work.
  - Explicitly excludes endpoint implementation, channel wiring, stream replay, observability UI, CPE/AgentShield enforcement, and customer-content inspection.
- Modify: `docs/observability/task-event-replay-readiness.md`
  - Updates Next Direction to point at `docs/observability/task-replay-adapter-readiness.md`.

No production code should change in this package.

### Task 1: Add Adapter Readiness RED Test

**Files:**
- Create: `tests/test_task_replay_adapter_readiness.py`
- Read: `docs/observability/task-event-replay-readiness.md`

- [ ] **Step 1: Write the failing test**

Create `tests/test_task_replay_adapter_readiness.py`:

```python
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-replay-adapter-readiness.md"
)
REPLAY_READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-replay-readiness.md"
)


REQUIRED_ADAPTER_READINESS_MARKERS = {
    "read-only TaskReplay adapter readiness",
    "TaskReplayService service contract already exists",
    "service-level replay DTO boundary",
    "panel/API/channel currently have no replay endpoint",
    "future read-only adapter must call TaskReplayService",
    "must not assemble timeline",
    "must not query TaskEventService",
    "must not connect to stream queues",
    "adapter DTO must pass through the service DTO",
    "does not implement stream runtime replay",
    "does not implement observability UI",
    "does not enable CPE or AgentShield enforcement",
    "does not inspect customer content",
    "endpoint implementation requires a separate small package",
}


def _adapter_readiness_text() -> str:
    assert ADAPTER_READINESS_DOC.exists(), (
        "docs/observability/task-replay-adapter-readiness.md is required"
    )
    return ADAPTER_READINESS_DOC.read_text(encoding="utf-8")


def test_task_replay_adapter_readiness_document_exists_and_defers_endpoint():
    text = _adapter_readiness_text()

    assert "read-only TaskReplay adapter readiness" in text
    assert "not implemented in this package" in text
    assert "endpoint implementation requires a separate small package" in text


def test_task_replay_adapter_readiness_document_names_required_boundaries():
    text = _adapter_readiness_text()
    missing = sorted(
        marker for marker in REQUIRED_ADAPTER_READINESS_MARKERS if marker not in text
    )

    assert missing == []


def test_task_event_replay_readiness_points_to_adapter_readiness_gate():
    text = REPLAY_READINESS_DOC.read_text(encoding="utf-8")

    assert "docs/observability/task-replay-adapter-readiness.md" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_task_replay_adapter_readiness.py -q
```

Expected: FAIL because `docs/observability/task-replay-adapter-readiness.md` does not exist and `task-event-replay-readiness.md` does not yet point to it.

### Task 2: Add Adapter Readiness Document

**Files:**
- Create: `docs/observability/task-replay-adapter-readiness.md`
- Modify: `docs/observability/task-event-replay-readiness.md`
- Test: `tests/test_task_replay_adapter_readiness.py`

- [ ] **Step 1: Add the readiness document**

Create `docs/observability/task-replay-adapter-readiness.md`:

```markdown
# Task Replay Adapter Readiness

## Readiness Decision

This document defines read-only TaskReplay adapter readiness.

panel, API, and channel replay endpoints are not implemented in this package.
endpoint implementation requires a separate small package.

## Existing Service Contract

TaskReplayService service contract already exists as the service-level replay DTO boundary over TaskTimelineService.

TaskReplayService normalizes limits, preserves TaskTimelineService event order, and returns stable missing and available replay DTOs.

panel/API/channel currently have no replay endpoint.

## Future Read-Only Adapter Boundary

Any future read-only adapter must call TaskReplayService.

The adapter DTO must pass through the service DTO, including:

- `trace_id`
- `found`
- `event_count`
- `source`
- `replay_status`
- `limit`
- `timeline`

A future adapter must not assemble timeline data itself.

A future adapter must not query TaskEventService.

A future adapter must not connect to stream queues.

TaskReplayService remains the only replay DTO source for adapter-facing read-only replay.

## Explicit Non-Goals

- no panel replay endpoint in this package;
- no API replay endpoint in this package;
- no channel replay adapter in this package;
- does not implement stream runtime replay;
- does not implement observability UI;
- does not enable CPE or AgentShield enforcement;
- does not inspect customer content;
- no TaskEventService schema change;
- no TaskTimelineService ordering or query change;
- no SessionRuntimeService change;
- no `feishu.route_callback` migration expansion.

## Verification Gate

TaskReplay adapter readiness is guarded by adapter readiness tests, task-event replay readiness tests, TaskReplayService tests, panel architecture tests, router/panel regression, and full pytest.

## Next Direction

If a read-only replay endpoint is needed, create a separate small implementation package that wires a panel or API adapter to TaskReplayService and keeps the adapter as pass-through only.

Stream runtime replay, observability UI, channel replay, governance enforcement, and customer-content inspection remain separate future decisions.
```

- [ ] **Step 2: Update replay readiness next direction**

Modify the `## Next Direction` section in `docs/observability/task-event-replay-readiness.md` to:

```markdown
## Next Direction

After this service contract remains green, the next package is `docs/observability/task-replay-adapter-readiness.md`.

That package should decide read-only adapter entry conditions before any panel/API endpoint is implemented. Stream runtime replay, observability UI, channel replay, CPE/AgentShield enforcement, and customer-content inspection remain out of scope until separate packages are approved.
```

- [ ] **Step 3: Run focused test to verify it passes**

Run:

```bash
pytest tests/test_task_replay_adapter_readiness.py -q
```

Expected: PASS.

### Task 3: Run Required Regression Gates

**Files:**
- Read: all modified files

- [ ] **Step 1: Run observability/service gate**

Run:

```bash
pytest tests/test_task_replay_adapter_readiness.py tests/test_task_event_replay_readiness.py tests/test_task_replay_service.py tests/test_task_timeline_service.py tests/test_task_event_service.py -q
```

Expected: PASS.

- [ ] **Step 2: Run panel/architecture gate**

Run:

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase5_closure_audit.py -q
```

Expected: PASS.

- [ ] **Step 3: Run router/panel regression**

Run:

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

Expected: PASS.

- [ ] **Step 4: Run full verification**

Run:

```bash
pytest -q
git diff --check
git status --short
```

Expected: pytest PASS, diff check clean, status shows only intended changed files before commit.

- [ ] **Step 5: Commit**

Run:

```bash
git add tests/test_task_replay_adapter_readiness.py docs/observability/task-replay-adapter-readiness.md docs/observability/task-event-replay-readiness.md docs/superpowers/plans/2026-05-27-task-replay-adapter-readiness.md
git commit -m "docs: add task replay adapter readiness gate"
```

Expected: commit succeeds.

## Self-Review

- Spec coverage: the plan covers the requested readiness doc, replay readiness next direction update, adapter boundary audit test, and required regression gates.
- Placeholder scan: no TBD/TODO/implement-later placeholders remain.
- Scope check: no endpoint, channel, stream runtime, observability UI, governance enforcement, sensitive content inspection, or old fallback expansion is included.
