# Observability Product Closeout Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the current observability productization route covering service replay, panel API, Feishu `/replay`, and Panel Observability UI V1.

**Architecture:** This package is documentation and architecture audit only. It records that the current product path uses persisted task timeline events through `TaskReplayService`, exposes read-only panel and Feishu adapters, and renders a read-only panel UI over the existing replay endpoint. It keeps API replay endpoint, advanced channel UX, advanced UI, stream runtime replay, queue restoration, governance enforcement, and customer-content inspection out of scope.

**Tech Stack:** Python pytest architecture audit tests, Markdown closeout docs.

---

## File Structure

- Create: `tests/test_observability_product_closeout_audit.py`
  - Requires `docs/observability/observability-product-closeout-status.md`.
  - Verifies completed productized observability surfaces and deferred advanced work.
  - Verifies related readiness/closeout docs point to the product closeout.
- Create: `docs/observability/observability-product-closeout-status.md`
  - Documents the completed observability product route and future-only work.
- Modify: `docs/observability/task-event-closeout-status.md`
  - Updates stale `no observability UI` text to V1-aware advanced UI deferral.
  - Points Next Direction to product closeout.
- Modify: `docs/architecture/final-closeout-status.md`
  - Updates stale `no observability UI` text to V1-aware advanced UI deferral.
  - Points Future Work to product closeout.
- Modify: `docs/observability/channel-replay-adapter-readiness.md`
  - Points Next Direction to product closeout.
- Modify: `docs/observability/observability-ui-readiness.md`
  - Points Next Direction to product closeout.
- Modify: `tests/test_architecture_final_closeout_audit.py`
  - Updates marker from `no observability UI` to `no advanced observability UI beyond Panel Observability UI V1`.
- Modify: `tests/test_task_event_closeout_audit.py`
  - Updates marker from `no observability UI` to `no advanced observability UI beyond Panel Observability UI V1`.

No production code should change in this package.

### Task 1: Add Product Closeout RED Test

**Files:**
- Create: `tests/test_observability_product_closeout_audit.py`

- [ ] **Step 1: Write failing audit test**

Create `tests/test_observability_product_closeout_audit.py`:

```python
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_CLOSEOUT_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "observability-product-closeout-status.md"
)
TASK_EVENT_CLOSEOUT_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-closeout-status.md"
)
CHANNEL_READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "channel-replay-adapter-readiness.md"
)
UI_READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "observability-ui-readiness.md"
)
FINAL_CLOSEOUT_DOC = PROJECT_ROOT / "docs" / "architecture" / "final-closeout-status.md"


REQUIRED_PRODUCT_CLOSEOUT_MARKERS = {
    "observability productization route is closed",
    "TaskReplayService owns the service-level replay DTO boundary",
    "panel `task_replay` handler calls TaskReplayService",
    "Feishu channel replay V1 is implemented",
    "ChannelReplayService",
    "Panel Observability UI V1 is implemented",
    "`/panel/api/tasks/{trace_id}/replay`",
    "Replay uses persisted task timeline events",
    "partial_output events may be displayed",
    "panel/API/channel remain adapters",
    "stream_snapshot remains in-process backlog only",
    "live SSE listener queues are not persisted or restored",
    "no API replay endpoint",
    "no advanced channel replay UX beyond Feishu `/replay <trace_id>` V1",
    "no advanced observability UI beyond Panel Observability UI V1",
    "no stream runtime replay",
    "no CPE or AgentShield enforcement",
    "no customer-content inspection",
}


def _product_closeout_text() -> str:
    assert PRODUCT_CLOSEOUT_DOC.exists(), (
        "docs/observability/observability-product-closeout-status.md is required"
    )
    return PRODUCT_CLOSEOUT_DOC.read_text(encoding="utf-8")


def test_observability_product_closeout_document_exists_and_declares_closed():
    text = _product_closeout_text()

    assert "observability productization route is closed" in text
    assert "Product Closeout Decision" in text


def test_observability_product_closeout_names_required_boundaries():
    text = _product_closeout_text()
    missing = sorted(
        marker for marker in REQUIRED_PRODUCT_CLOSEOUT_MARKERS if marker not in text
    )

    assert missing == []


def test_related_observability_docs_point_to_product_closeout():
    required_link = "docs/observability/observability-product-closeout-status.md"

    for path in (
        TASK_EVENT_CLOSEOUT_DOC,
        CHANNEL_READINESS_DOC,
        UI_READINESS_DOC,
        FINAL_CLOSEOUT_DOC,
    ):
        text = path.read_text(encoding="utf-8")
        assert required_link in text
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_observability_product_closeout_audit.py -q
```

Expected: FAIL because the product closeout document does not exist and related docs do not point to it.

### Task 2: Add Product Closeout Document and Update References

**Files:**
- Create: `docs/observability/observability-product-closeout-status.md`
- Modify docs/tests listed above.

- [ ] **Step 1: Create product closeout document**

Create `docs/observability/observability-product-closeout-status.md`:

```markdown
# Observability Product Closeout Status

## Product Closeout Decision

The observability productization route is closed.

This closeout covers service-level replay DTOs, the panel replay adapter, Feishu channel replay V1, and Panel Observability UI V1.

No new runtime behavior is added in this closeout package.

## Completed Product Surfaces

TaskReplayService owns the service-level replay DTO boundary.

The panel `task_replay` handler calls TaskReplayService.

Feishu channel replay V1 is implemented through ChannelReplayService and explicit `/replay <trace_id>` commands.

Panel Observability UI V1 is implemented through the existing `/panel/api/tasks/{trace_id}/replay` adapter.

Panel Observability UI V1 can display persisted timeline events and partial_output events may be displayed from the replay DTO.

panel/API/channel remain adapters.

Replay uses persisted task timeline events.

## Runtime Boundary

stream_snapshot remains in-process backlog only.

live SSE listener queues are not persisted or restored.

Replay does not reconstruct live SSE listener queues.

## Deferred Work

- no API replay endpoint;
- no advanced channel replay UX beyond Feishu `/replay <trace_id>` V1;
- no advanced observability UI beyond Panel Observability UI V1;
- no stream runtime replay;
- no live SSE listener queue persistence or restoration;
- no CPE or AgentShield enforcement;
- no customer-content inspection;
- no TaskEventService schema change;
- no TaskTimelineService ordering or query change;
- no SessionRuntimeService change.

## Verification Gate

Observability product closeout is guarded by product closeout audit tests, task-event closeout tests, channel replay readiness tests, observability UI readiness tests, panel UI tests, TaskReplayService tests, ChannelReplayService tests, panel architecture tests, router/panel regression, and full pytest.

## Next Direction

Future API replay endpoint, advanced channel replay UX, advanced observability UI, stream runtime replay, governance enforcement, and customer-content inspection require separate product decisions and implementation plans.
```

- [ ] **Step 2: Update docs and tests**

In `docs/observability/task-event-closeout-status.md` and `docs/architecture/final-closeout-status.md`, replace `no observability UI` with:

```markdown
no advanced observability UI beyond Panel Observability UI V1
```

Add `docs/observability/observability-product-closeout-status.md` links to task-event closeout, channel replay readiness, observability UI readiness, and architecture final closeout.

Update test markers in `tests/test_architecture_final_closeout_audit.py` and `tests/test_task_event_closeout_audit.py` to use the new advanced UI marker.

- [ ] **Step 3: Run GREEN focused**

Run:

```bash
pytest tests/test_observability_product_closeout_audit.py tests/test_task_event_closeout_audit.py tests/test_architecture_final_closeout_audit.py -q
```

Expected: PASS.

### Task 3: Regression Verification and Commit

**Files:** Test/docs only.

- [ ] **Step 1: Run focused observability docs/UI suites**

Run:

```bash
pytest tests/test_observability_product_closeout_audit.py tests/test_observability_ui_readiness.py tests/test_panel_observability_ui.py tests/test_channel_replay_adapter_readiness.py tests/test_task_event_closeout_audit.py -q
```

Expected: PASS.

- [ ] **Step 2: Run observability/service regression**

Run:

```bash
pytest tests/test_task_replay_service.py tests/test_task_timeline_service.py tests/test_task_event_service.py tests/test_channel_replay_service.py tests/test_observability_product_closeout_audit.py -q
```

Expected: PASS.

- [ ] **Step 3: Run panel/architecture regression**

Run:

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase5_closure_audit.py tests/test_architecture_final_closeout_audit.py tests/test_panel_observability_ui.py -q
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
git add tests/test_observability_product_closeout_audit.py tests/test_architecture_final_closeout_audit.py tests/test_task_event_closeout_audit.py docs/observability/observability-product-closeout-status.md docs/observability/task-event-closeout-status.md docs/observability/channel-replay-adapter-readiness.md docs/observability/observability-ui-readiness.md docs/architecture/final-closeout-status.md docs/superpowers/plans/2026-05-28-observability-product-closeout-audit.md
git commit -m "docs: close observability product route"
```

Expected: commit succeeds.

## Self-Review

- Spec coverage: this plan closes the productized observability route after service replay, panel replay API, Feishu replay, and panel replay UI are implemented.
- Placeholder scan: no TBD, TODO, or open implementation placeholders.
- Scope check: no production code, API replay endpoint, advanced UI, advanced channel UX, stream runtime replay, live SSE queue persistence, governance enforcement, customer-content inspection, schema/query/order changes, or SessionRuntimeService changes are included.
