# Feishu Route Callback Deletion Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a readiness gate for future Feishu `route_callback` fallback deletion without deleting the fallback or expanding legacy behavior.

**Architecture:** `ChannelHub` owns Feishu channel lifecycle and standard `ChannelMessage` routing. `FeishuAdapter` currently prefers `message_callback` and keeps `route_callback` as a bounded migration fallback. This package only documents deletion conditions and blockers: deletion requires a separate implementation package after all supported Feishu inbound paths use `ChannelMessage` and compatibility fallback tests can be removed deliberately.

**Tech Stack:** Python pytest architecture audit tests, Markdown readiness docs.

---

## File Structure

- Create: `tests/test_feishu_route_callback_deletion_readiness.py`
  - Requires `docs/phase4/feishu-route-callback-deletion-readiness.md`.
  - Verifies current fallback status, deletion blockers, explicit non-goals, and links from closure/closeout docs.
- Create: `docs/phase4/feishu-route-callback-deletion-readiness.md`
  - Documents readiness decision: not deleted in this package.
  - Lists deletion blockers and future deletion package requirements.
- Modify: `docs/phase4/phase-4-closure-status.md`
  - Updates Next Direction / compatibility notes to point to deletion readiness.
- Modify: `docs/observability/task-event-closeout-status.md`
  - Updates Next Direction entry to point to deletion readiness.

No production code should change in this package.

### Task 1: Add RED Deletion Readiness Audit

**Files:**
- Create: `tests/test_feishu_route_callback_deletion_readiness.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_feishu_route_callback_deletion_readiness.py`:

```python
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
READINESS_DOC = PROJECT_ROOT / "docs" / "phase4" / "feishu-route-callback-deletion-readiness.md"
PHASE4_CLOSURE_DOC = PROJECT_ROOT / "docs" / "phase4" / "phase-4-closure-status.md"
TASK_EVENT_CLOSEOUT_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-closeout-status.md"
)


REQUIRED_DELETION_READINESS_MARKERS = {
    "Feishu route_callback deletion readiness",
    "`feishu.route_callback` remains a bounded migration fallback",
    "not deleted in this package",
    "ChannelHub owns Feishu channel lifecycle",
    "FeishuAdapter prefers `message_callback` over `route_callback`",
    "standard inbound path uses `ChannelMessage`",
    "legacy fallback path still exists",
    "all supported Feishu inbound paths use `ChannelMessage`",
    "remove `route_callback` construction from ChannelHub",
    "remove fallback execution from FeishuAdapter",
    "remove legacy fallback tests deliberately",
    "no new Feishu business behavior",
    "no route_stream fallback expansion",
    "no channel replay adapter",
    "no observability UI",
    "no CPE or AgentShield enforcement",
    "no customer-content inspection",
}


def _readiness_text() -> str:
    assert READINESS_DOC.exists(), (
        "docs/phase4/feishu-route-callback-deletion-readiness.md is required"
    )
    return READINESS_DOC.read_text(encoding="utf-8")


def test_feishu_route_callback_deletion_readiness_document_exists_and_defers_deletion():
    text = _readiness_text()

    assert "Feishu route_callback deletion readiness" in text
    assert "`feishu.route_callback` remains a bounded migration fallback" in text
    assert "not deleted in this package" in text


def test_feishu_route_callback_deletion_readiness_names_required_boundaries():
    text = _readiness_text()
    missing = sorted(
        marker for marker in REQUIRED_DELETION_READINESS_MARKERS if marker not in text
    )

    assert missing == []


def test_phase4_closure_points_to_feishu_route_callback_deletion_readiness():
    text = PHASE4_CLOSURE_DOC.read_text(encoding="utf-8")

    assert "docs/phase4/feishu-route-callback-deletion-readiness.md" in text


def test_task_event_closeout_points_to_feishu_route_callback_deletion_readiness():
    text = TASK_EVENT_CLOSEOUT_DOC.read_text(encoding="utf-8")

    assert "docs/phase4/feishu-route-callback-deletion-readiness.md" in text
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_feishu_route_callback_deletion_readiness.py -q
```

Expected: FAIL because `docs/phase4/feishu-route-callback-deletion-readiness.md` does not exist and linked docs do not point to it.

### Task 2: Add Readiness Document and Links

**Files:**
- Create: `docs/phase4/feishu-route-callback-deletion-readiness.md`
- Modify: `docs/phase4/phase-4-closure-status.md`
- Modify: `docs/observability/task-event-closeout-status.md`

- [ ] **Step 1: Create deletion readiness doc**

Create `docs/phase4/feishu-route-callback-deletion-readiness.md`:

```markdown
# Feishu Route Callback Deletion Readiness

## Readiness Decision

This document defines Feishu route_callback deletion readiness.

`feishu.route_callback` remains a bounded migration fallback and is not deleted in this package.

## Current Boundaries

ChannelHub owns Feishu channel lifecycle, status, and standard message routing glue.

The standard inbound path uses `ChannelMessage`.

FeishuAdapter prefers `message_callback` over `route_callback`.

The legacy fallback path still exists through `route_callback`.

The compatibility boundary remains explicit in ChannelHub with status `migration_fallback`.

## Deletion Blockers

Deletion is blocked until all supported Feishu inbound paths use `ChannelMessage`.

Deletion is blocked while compatibility fallback tests still document supported legacy behavior.

Deletion is blocked until startup and panel Feishu lifecycle paths remain green without relying on route_callback fallback behavior.

## Future Deletion Package Requirements

A future deletion package must:

- remove `route_callback` construction from ChannelHub;
- remove fallback execution from FeishuAdapter;
- remove legacy fallback tests deliberately;
- keep the standard `message_callback` / `ChannelMessage` path green;
- keep Feishu discussion stop handling behind ChannelHub;
- keep panel and startup code as adapters.

## Explicit Non-Goals

- no deletion in this package;
- no new Feishu business behavior;
- no route_stream fallback expansion;
- no channel replay adapter;
- no observability UI;
- no CPE or AgentShield enforcement;
- no customer-content inspection;
- no TaskEventService schema change;
- no SessionRuntimeService change.

## Verification Gate

Feishu route_callback deletion readiness is guarded by readiness audit tests, ChannelHub tests, Feishu adapter tests, Phase 4 closure tests, panel architecture tests, router/panel regression, and full pytest.

## Next Direction

If Feishu fallback cleanup remains the priority, the next package should be a deletion implementation plan that removes the fallback only after this readiness gate stays green.
```

- [ ] **Step 2: Update Phase 4 closure**

In `docs/phase4/phase-4-closure-status.md`, add to Compatibility Boundaries:

```markdown
- Feishu `route_callback` deletion readiness is tracked in `docs/phase4/feishu-route-callback-deletion-readiness.md`.
```

Replace the `## Next Direction` body with:

```markdown
Phase 5 and observability/task-event closeout are complete.

Feishu `route_callback` fallback deletion readiness is tracked in `docs/phase4/feishu-route-callback-deletion-readiness.md`.
```

- [ ] **Step 3: Update task-event closeout next direction**

In `docs/observability/task-event-closeout-status.md`, replace:

```markdown
- Feishu `route_callback` fallback deletion readiness.
```

with:

```markdown
- Feishu `route_callback` fallback deletion readiness in `docs/phase4/feishu-route-callback-deletion-readiness.md`.
```

- [ ] **Step 4: Run GREEN focused test**

Run:

```bash
pytest tests/test_feishu_route_callback_deletion_readiness.py -q
```

Expected: PASS.

### Task 3: Run Required Regression Gates

**Files:**
- Read: all modified files

- [ ] **Step 1: Run focused readiness/closure tests**

Run:

```bash
pytest tests/test_feishu_route_callback_deletion_readiness.py tests/test_phase4_closure_audit.py tests/test_task_event_closeout_audit.py -q
```

Expected: PASS.

- [ ] **Step 2: Run channel/feishu gate**

Run:

```bash
pytest tests/test_channel_hub.py tests/test_feishu_channel.py tests/test_feishu_path.py -q
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
git add tests/test_feishu_route_callback_deletion_readiness.py docs/phase4/feishu-route-callback-deletion-readiness.md docs/phase4/phase-4-closure-status.md docs/observability/task-event-closeout-status.md docs/superpowers/plans/2026-05-28-feishu-route-callback-deletion-readiness.md
git commit -m "docs: add feishu route callback deletion readiness"
```

Expected: commit succeeds.

## Self-Review

- Spec coverage: the plan adds deletion readiness only and links it from Phase 4 and task-event closeout docs.
- Placeholder scan: no TBD/TODO/implement-later placeholders remain.
- Scope check: no production code, no fallback deletion, no legacy fallback expansion, no channel replay, no observability UI, no governance enforcement, no customer-content inspection, no TaskEventService schema change, and no SessionRuntimeService change is included.
