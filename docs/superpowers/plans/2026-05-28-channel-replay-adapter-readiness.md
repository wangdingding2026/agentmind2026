# Channel Replay Adapter Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a readiness gate for a future read-only channel replay adapter, optimized for Feishu V1, without implementing channel commands or changing runtime behavior.

**Architecture:** This package is documentation and architecture audit only. It records that a future channel replay adapter should be a narrow read-only adapter over `TaskReplayService`, with Feishu V1 using explicit `/replay <trace_id>` commands and concise message formatting. It prevents channel/Feishu code from assembling timelines, querying `TaskEventService`, using stream queues, enabling governance enforcement, or inspecting customer content.

**Tech Stack:** Python pytest architecture audit tests, Markdown readiness docs.

---

## File Structure

- Create: `tests/test_channel_replay_adapter_readiness.py`
  - Requires `docs/observability/channel-replay-adapter-readiness.md`.
  - Verifies the future channel replay adapter boundary and Feishu V1 UX constraints.
  - Verifies final closeout and task-event closeout docs point to this readiness gate.
- Create: `docs/observability/channel-replay-adapter-readiness.md`
  - Documents why channel replay is useful, how to keep V1 constrained, and what is out of scope.
- Modify: `docs/architecture/final-closeout-status.md`
  - Updates Future Work to point channel replay adapter to the readiness gate.
- Modify: `docs/observability/task-event-closeout-status.md`
  - Updates Next Direction to point channel replay adapter to the readiness gate.

No production code should change in this package.

### Task 1: Add Channel Replay Adapter RED Test

**Files:**
- Create: `tests/test_channel_replay_adapter_readiness.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_channel_replay_adapter_readiness.py`:

```python
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "channel-replay-adapter-readiness.md"
)
FINAL_CLOSEOUT_DOC = PROJECT_ROOT / "docs" / "architecture" / "final-closeout-status.md"
TASK_EVENT_CLOSEOUT_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-closeout-status.md"
)


REQUIRED_CHANNEL_REPLAY_READINESS_MARKERS = {
    "channel replay adapter readiness",
    "future read-only channel replay adapter",
    "Feishu V1",
    "`/replay <trace_id>`",
    "explicit command only",
    "must call TaskReplayService",
    "must not assemble timeline",
    "must not query TaskEventService",
    "must not connect to stream queues",
    "must not reconstruct live SSE listener queues",
    "must not implement stream runtime replay",
    "must not implement observability UI",
    "must not enable CPE or AgentShield enforcement",
    "must not inspect customer content",
    "adapter DTO must be derived from the TaskReplayService DTO",
    "concise text summary",
    "bounded event count",
    "no natural-language 'last task' resolution",
    "no pagination in V1",
    "no Feishu card UI in V1",
    "no API replay endpoint",
    "implementation requires a separate small package",
}


def _readiness_text() -> str:
    assert READINESS_DOC.exists(), (
        "docs/observability/channel-replay-adapter-readiness.md is required"
    )
    return READINESS_DOC.read_text(encoding="utf-8")


def test_channel_replay_adapter_readiness_document_exists_and_defers_implementation():
    text = _readiness_text()

    assert "channel replay adapter readiness" in text
    assert "implementation requires a separate small package" in text


def test_channel_replay_adapter_readiness_names_required_boundaries():
    text = _readiness_text()
    missing = sorted(
        marker
        for marker in REQUIRED_CHANNEL_REPLAY_READINESS_MARKERS
        if marker not in text
    )

    assert missing == []


def test_final_closeout_points_to_channel_replay_adapter_readiness():
    text = FINAL_CLOSEOUT_DOC.read_text(encoding="utf-8")

    assert "docs/observability/channel-replay-adapter-readiness.md" in text


def test_task_event_closeout_points_to_channel_replay_adapter_readiness():
    text = TASK_EVENT_CLOSEOUT_DOC.read_text(encoding="utf-8")

    assert "docs/observability/channel-replay-adapter-readiness.md" in text
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_channel_replay_adapter_readiness.py -q
```

Expected: FAIL because `docs/observability/channel-replay-adapter-readiness.md` does not exist and closeout docs do not point to it.

### Task 2: Add Readiness Document and Next Direction Updates

**Files:**
- Create: `docs/observability/channel-replay-adapter-readiness.md`
- Modify: `docs/architecture/final-closeout-status.md`
- Modify: `docs/observability/task-event-closeout-status.md`

- [ ] **Step 1: Create readiness document**

Create `docs/observability/channel-replay-adapter-readiness.md`:

```markdown
# Channel Replay Adapter Readiness

## Readiness Decision

This document defines channel replay adapter readiness.

A future read-only channel replay adapter is useful for Feishu users who need task replay diagnostics without opening the panel.

This package does not implement the channel replay adapter. Channel replay adapter implementation requires a separate small package.

## Feishu V1 UX Boundary

Feishu V1 should support `/replay <trace_id>`.

The command is explicit command only.

The adapter should return a concise text summary.

The summary should use a bounded event count.

Feishu V1 has no natural-language 'last task' resolution.

Feishu V1 has no pagination in V1.

Feishu V1 has no Feishu card UI in V1.

## Adapter Boundary

A future read-only channel replay adapter must call TaskReplayService.

The adapter DTO must be derived from the TaskReplayService DTO.

The adapter must not assemble timeline data.

The adapter must not query TaskEventService.

The adapter must not connect to stream queues.

The adapter must not reconstruct live SSE listener queues.

TaskReplayService remains the replay DTO source for channel-facing read-only replay.

## Explicit Non-Goals

- no channel replay implementation in this package;
- no API replay endpoint;
- no observability UI;
- no stream runtime replay;
- no live SSE listener queue persistence or restoration;
- no CPE or AgentShield enforcement;
- no customer-content inspection;
- no natural-language task lookup;
- no cross-channel replay routing;
- no Feishu card UI;
- no pagination;
- no TaskEventService schema change;
- no TaskTimelineService ordering or query change;
- no SessionRuntimeService change.

## Verification Gate

Channel replay adapter readiness is guarded by readiness audit tests, task-event closeout tests, architecture final closeout tests, ChannelHub tests, Feishu adapter tests, panel architecture tests, router/panel regression, and full pytest.

## Next Direction

If channel replay is selected for implementation, start with a separate Feishu `/replay <trace_id>` V1 package.

That implementation must keep FeishuAdapter as a protocol adapter, keep ChannelHub as channel glue, and call TaskReplayService for replay data.
```

- [ ] **Step 2: Update closeout references**

In `docs/architecture/final-closeout-status.md`, update the channel replay future-work bullet to:

```markdown
- channel replay adapter, after `docs/observability/channel-replay-adapter-readiness.md`;
```

In `docs/observability/task-event-closeout-status.md`, add this sentence under `## Next Direction`:

```markdown
Channel replay adapter readiness is tracked in `docs/observability/channel-replay-adapter-readiness.md`.
```

- [ ] **Step 3: Run GREEN**

Run:

```bash
pytest tests/test_channel_replay_adapter_readiness.py -q
```

Expected: PASS.

### Task 3: Regression Verification and Commit

**Files:**
- Test only.

- [ ] **Step 1: Run focused readiness suites**

Run:

```bash
pytest tests/test_channel_replay_adapter_readiness.py tests/test_architecture_final_closeout_audit.py tests/test_task_event_closeout_audit.py -q
```

Expected: PASS.

- [ ] **Step 2: Run observability/service regression**

Run:

```bash
pytest tests/test_channel_replay_adapter_readiness.py tests/test_task_replay_adapter_readiness.py tests/test_task_event_replay_readiness.py tests/test_task_replay_service.py tests/test_task_timeline_service.py tests/test_task_event_service.py -q
```

Expected: PASS.

- [ ] **Step 3: Run channel/Feishu regression**

Run:

```bash
pytest tests/test_channel_hub.py tests/test_feishu_channel.py tests/test_feishu_path.py tests/test_feishu_route_callback_deletion_readiness.py -q
```

Expected: PASS.

- [ ] **Step 4: Run panel/architecture regression**

Run:

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase5_closure_audit.py tests/test_architecture_final_closeout_audit.py -q
```

Expected: PASS.

- [ ] **Step 5: Run router/panel regression**

Run:

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

Expected: PASS.

- [ ] **Step 6: Run full validation**

Run:

```bash
pytest -q
git diff --check
git status --short
```

Expected: full pytest PASS, whitespace check clean, and only intended files changed before commit.

- [ ] **Step 7: Commit**

Run:

```bash
git add tests/test_channel_replay_adapter_readiness.py docs/observability/channel-replay-adapter-readiness.md docs/architecture/final-closeout-status.md docs/observability/task-event-closeout-status.md docs/superpowers/plans/2026-05-28-channel-replay-adapter-readiness.md
git commit -m "docs: add channel replay adapter readiness"
```

Expected: commit succeeds.

## Self-Review

- Spec coverage: this plan covers Feishu V1 UX constraints, channel adapter boundaries, closeout references, focused and regression verification, and commit.
- Placeholder scan: no TBD, TODO, or open implementation placeholders.
- Scope check: no production code, channel command implementation, API replay endpoint, observability UI, stream runtime replay, live SSE queue persistence, governance enforcement, customer-content inspection, natural-language task lookup, Feishu card UI, pagination, schema/query/order changes, or SessionRuntimeService changes are included.
