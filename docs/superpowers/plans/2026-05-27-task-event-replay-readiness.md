# Task Event Replay Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define the readiness gate for future persistent task-event replay without implementing replay behavior.

**Architecture:** TaskEventService owns stored task timeline events, TaskTimelineService owns read-side DTO assembly, and future replay must sit behind a service boundary. Panel/API/channel/stream runtime remain adapters or runtime transports and must not reconstruct replay from live SSE listener queues.

**Tech Stack:** pytest architecture audit tests, Markdown architecture documents, existing observability/task-event service boundaries.

---

## Scope

Create:

- `docs/observability/task-event-replay-readiness.md`
- `tests/test_task_event_replay_readiness.py`
- `docs/superpowers/plans/2026-05-27-task-event-replay-readiness.md`

Modify:

- `docs/observability/task-event-readiness.md`

Do not modify:

- `src/agentmind/services/task_event_service.py`
- `src/agentmind/services/task_timeline_service.py`
- `src/agentmind/services/session_runtime_service.py`
- `src/agentmind/panel/server.py`
- stream runtime behavior
- panel UI
- API/channel behavior

## Behavior

This package documents and guards the future replay entry conditions:

- replay remains future work;
- replay must use persisted TaskEventService task timeline events;
- replay must not reconstruct live SSE listener queues;
- stream_snapshot remains an in-process backlog boundary;
- TaskTimelineService remains the read-side DTO boundary;
- any future replay service must be service-level before panel/API/channel adapters consume it;
- no observability UI, no stream runtime mutation, no CPE/AgentShield enforcement, and no customer-content inspection are introduced here.

## Task 1: RED Replay Readiness Audit

**Files:**

- Create: `tests/test_task_event_replay_readiness.py`

- [ ] **Step 1: Add failing readiness audit test**

Create the file with the following content:

```python
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPLAY_READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-replay-readiness.md"
)
TASK_EVENT_READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-readiness.md"
)


REQUIRED_REPLAY_READINESS_MARKERS = {
    "task-event replay readiness",
    "future persistent task-event replay",
    "TaskEventService owns stored task timeline events",
    "TaskTimelineService remains the read-side DTO boundary",
    "Replay must use persisted task timeline events",
    "Replay must not reconstruct live SSE listener queues",
    "stream_snapshot remains an in-process backlog boundary",
    "future TaskReplayService",
    "service-level boundary before panel/API/channel adapters",
    "no observability UI",
    "no stream runtime behavior changes",
    "no panel/API/channel replay assembly",
    "no CPE or AgentShield enforcement",
    "no customer-content inspection",
}


def _replay_readiness_text() -> str:
    assert REPLAY_READINESS_DOC.exists(), (
        "docs/observability/task-event-replay-readiness.md is required"
    )
    return REPLAY_READINESS_DOC.read_text(encoding="utf-8")


def test_task_event_replay_readiness_document_exists_and_defers_replay():
    text = _replay_readiness_text()

    assert "task-event replay readiness" in text
    assert "future persistent task-event replay" in text
    assert "not implemented in this package" in text


def test_task_event_replay_readiness_document_names_required_boundaries():
    text = _replay_readiness_text()
    missing = sorted(
        marker for marker in REQUIRED_REPLAY_READINESS_MARKERS if marker not in text
    )

    assert missing == []


def test_task_event_readiness_points_to_replay_readiness_gate():
    text = TASK_EVENT_READINESS_DOC.read_text(encoding="utf-8")

    assert "docs/observability/task-event-replay-readiness.md" in text
```

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_task_event_replay_readiness.py -q
```

Expected: FAIL because `docs/observability/task-event-replay-readiness.md` does not exist and `docs/observability/task-event-readiness.md` does not yet point to it.

## Task 2: GREEN Replay Readiness Document

**Files:**

- Create: `docs/observability/task-event-replay-readiness.md`
- Modify: `docs/observability/task-event-readiness.md`

- [ ] **Step 1: Create replay readiness document**

Create `docs/observability/task-event-replay-readiness.md` with sections:

```markdown
# Task Event Replay Readiness

## Readiness Decision

This document defines task-event replay readiness.

future persistent task-event replay is not implemented in this package.

## Existing Boundaries

TaskEventService owns stored task timeline events.

TaskTimelineService remains the read-side DTO boundary over TaskEventService events.

TaskExplanationService may include timeline DTOs through TaskTimelineService.

panel/API/channel remain adapters and must not assemble replay timelines.

## Future Replay Boundary

Replay must use persisted task timeline events.

Replay must not reconstruct live SSE listener queues.

stream_snapshot remains an in-process backlog boundary.

future TaskReplayService should own replay orchestration as a service-level boundary before panel/API/channel adapters consume it.

## Entry Conditions

- TaskEventService event vocabulary remains stable.
- TaskEventService event ordering remains trace-id and creation-time based.
- TaskTimelineService DTO shape remains stable for missing and found timelines.
- Any future replay service starts service-level before panel/API/channel adapters are changed.

## Explicit Non-Goals

- no observability UI in this package;
- no stream runtime behavior changes;
- no panel/API/channel replay assembly;
- no CPE or AgentShield enforcement;
- no customer-content inspection;
- no replay persistence migration.

## Verification Gate

Replay readiness is guarded by task-event replay readiness tests, task-event observability readiness tests, Phase 5 closure tests, panel architecture tests, router/panel regression, and full pytest.

## Next Direction

After this readiness gate, the next package can add a minimal service-level TaskReplayService plan and RED tests. That package should still avoid panel UI and stream runtime changes until the service boundary is proven.
```

- [ ] **Step 2: Update task-event readiness next direction**

In `docs/observability/task-event-readiness.md`, replace the stale next direction that mentions adding the TaskEventService skeleton with a pointer to:

```markdown
After the task event service, timeline query, explanation, and panel adapter boundaries remain green, the next package is `docs/observability/task-event-replay-readiness.md`.
```

- [ ] **Step 3: Run GREEN focused test**

```bash
pytest tests/test_task_event_replay_readiness.py -q
```

Expected: PASS.

## Task 3: Regression Verification

**Files:**

- No additional edits expected.

- [ ] **Step 1: Run observability focused tests**

```bash
pytest tests/test_task_event_replay_readiness.py tests/test_observability_task_event_readiness.py tests/test_task_event_service.py tests/test_task_timeline_service.py tests/test_task_explanation_service.py -q
```

- [ ] **Step 2: Run phase/panel architecture regression**

```bash
pytest tests/test_phase5_closure_audit.py tests/test_panel_control_plane_boundary.py tests/test_panel_api.py -q
```

- [ ] **Step 3: Run router/panel regression**

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

- [ ] **Step 4: Run full verification**

```bash
pytest -q
git diff --check
git status --short
```

## Task 4: Commit

**Files:**

- Commit all changed files.

- [ ] **Step 1: Commit**

```bash
git add docs/superpowers/plans/2026-05-27-task-event-replay-readiness.md docs/observability/task-event-replay-readiness.md docs/observability/task-event-readiness.md tests/test_task_event_replay_readiness.py
git commit -m "docs: add task event replay readiness gate"
```
