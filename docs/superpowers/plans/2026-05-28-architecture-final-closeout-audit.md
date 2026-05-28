# Architecture Final Closeout Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an overall architecture final closeout audit for the completed AgentMind refactor route, covering Phase 1-5, observability/task-event closeout, and Feishu route_callback fallback deletion without adding runtime behavior.

**Architecture:** This package is documentation and architecture audit only. It records that service-layer, platform-core, control-panel/channel, permissive governance, task-event observability, replay adapter, and Feishu fallback deletion boundaries are closed. Future API replay, channel replay, observability UI, governance enforcement, customer-content inspection, self-evolution, and TemplateMarket remain separate product decisions.

**Tech Stack:** Python pytest architecture audit tests, Markdown closeout docs.

---

## File Structure

- Create: `tests/test_architecture_final_closeout_audit.py`
  - Requires `docs/architecture/final-closeout-status.md`.
  - Verifies phase closure, task-event closeout, Feishu fallback deletion, adapter/service boundaries, and deferred work.
  - Verifies existing phase/observability closeout docs point to the final closeout.
- Create: `docs/architecture/final-closeout-status.md`
  - Documents the overall architecture closeout decision.
  - Names completed boundaries and explicit deferred/non-goal work.
- Modify: `docs/observability/task-event-closeout-status.md`
  - Updates Next Direction to point to `docs/architecture/final-closeout-status.md`.
- Modify: `docs/phase4/feishu-route-callback-deletion-readiness.md`
  - Updates Next Direction to point to `docs/architecture/final-closeout-status.md`.
- Modify: `docs/phase5/phase-5-closure-status.md`
  - Updates Next Direction to point to `docs/architecture/final-closeout-status.md`.

No production code should change in this package.

### Task 1: Add Final Closeout RED Test

**Files:**
- Create: `tests/test_architecture_final_closeout_audit.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_architecture_final_closeout_audit.py`:

```python
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FINAL_CLOSEOUT_DOC = PROJECT_ROOT / "docs" / "architecture" / "final-closeout-status.md"
PHASE3_CLOSURE_DOC = PROJECT_ROOT / "docs" / "phase3" / "phase-3-closure-status.md"
PHASE4_CLOSURE_DOC = PROJECT_ROOT / "docs" / "phase4" / "phase-4-closure-status.md"
PHASE5_CLOSURE_DOC = PROJECT_ROOT / "docs" / "phase5" / "phase-5-closure-status.md"
TASK_EVENT_CLOSEOUT_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-closeout-status.md"
)
FEISHU_DELETION_DOC = (
    PROJECT_ROOT / "docs" / "phase4" / "feishu-route-callback-deletion-readiness.md"
)


REQUIRED_FINAL_CLOSEOUT_MARKERS = {
    "AgentMind architecture refactor route is closed",
    "Phase 1 service-layer foundation is complete",
    "Phase 2 memory and trace convergence is complete",
    "Phase 3 platform-core and control-plane service boundaries are closed",
    "Phase 4 control-panel runtime and channel boundary work is closed",
    "Phase 5 permissive governance architecture baseline is closed",
    "observability/task-event route is closed",
    "Feishu `route_callback` fallback has been removed",
    "services do the work",
    "rule/core layers own rules and decisions",
    "panel/API/channel remain adapters",
    "TaskEventService owns stored task timeline events",
    "TaskTimelineService owns read-side timeline DTO assembly",
    "TaskReplayService owns the service-level replay DTO boundary",
    "panel `task_replay` handler calls TaskReplayService",
    "stream_snapshot remains in-process backlog only",
    "live SSE listener queues are not persisted or restored",
    "CPE remains permissive",
    "AgentShield remains permissive",
    "content_inspection=false",
    "behavior_inspection=false",
    "no customer-content inspection",
    "no CPE or AgentShield enforcement",
    "no self-evolution work",
    "no TemplateMarket work",
    "no API replay endpoint",
    "no channel replay adapter",
    "no observability UI",
    "no stream runtime replay",
    "future packages require separate implementation plans",
}


def _final_closeout_text() -> str:
    assert FINAL_CLOSEOUT_DOC.exists(), (
        "docs/architecture/final-closeout-status.md is required"
    )
    return FINAL_CLOSEOUT_DOC.read_text(encoding="utf-8")


def test_architecture_final_closeout_document_exists_and_declares_closed():
    text = _final_closeout_text()

    assert "AgentMind architecture refactor route is closed" in text
    assert "Final Closeout Decision" in text


def test_architecture_final_closeout_document_names_required_boundaries():
    text = _final_closeout_text()
    missing = sorted(
        marker for marker in REQUIRED_FINAL_CLOSEOUT_MARKERS if marker not in text
    )

    assert missing == []


def test_final_closeout_links_to_required_closure_sources():
    text = _final_closeout_text()

    assert "docs/phase3/phase-3-closure-status.md" in text
    assert "docs/phase4/phase-4-closure-status.md" in text
    assert "docs/phase5/phase-5-closure-status.md" in text
    assert "docs/observability/task-event-closeout-status.md" in text
    assert "docs/phase4/feishu-route-callback-deletion-readiness.md" in text


def test_recent_closure_docs_point_to_final_closeout():
    required_link = "docs/architecture/final-closeout-status.md"

    for path in (
        PHASE5_CLOSURE_DOC,
        TASK_EVENT_CLOSEOUT_DOC,
        FEISHU_DELETION_DOC,
    ):
        text = path.read_text(encoding="utf-8")
        assert required_link in text


def test_historical_closure_docs_remain_available_as_sources():
    for path in (
        PHASE3_CLOSURE_DOC,
        PHASE4_CLOSURE_DOC,
        PHASE5_CLOSURE_DOC,
        TASK_EVENT_CLOSEOUT_DOC,
        FEISHU_DELETION_DOC,
    ):
        assert path.exists()
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_architecture_final_closeout_audit.py -q
```

Expected: FAIL because `docs/architecture/final-closeout-status.md` does not exist and recent closeout docs do not point to it.

### Task 2: Add Final Closeout Document and Next Direction Updates

**Files:**
- Create: `docs/architecture/final-closeout-status.md`
- Modify: `docs/observability/task-event-closeout-status.md`
- Modify: `docs/phase4/feishu-route-callback-deletion-readiness.md`
- Modify: `docs/phase5/phase-5-closure-status.md`

- [ ] **Step 1: Create final closeout status document**

Create `docs/architecture/final-closeout-status.md`:

```markdown
# Architecture Final Closeout Status

## Final Closeout Decision

AgentMind architecture refactor route is closed.

This final closeout summarizes the completed refactor route across Phase 1-5, observability/task-event closeout, and Feishu `route_callback` fallback deletion.

No production runtime behavior is added in this package.

## Closure Sources

- Phase 3 platform-core/control-plane closure: `docs/phase3/phase-3-closure-status.md`.
- Phase 4 channel/runtime closure: `docs/phase4/phase-4-closure-status.md`.
- Phase 5 governance closure: `docs/phase5/phase-5-closure-status.md`.
- Task-event observability closeout: `docs/observability/task-event-closeout-status.md`.
- Feishu fallback deletion status: `docs/phase4/feishu-route-callback-deletion-readiness.md`.

## Completed Route

Phase 1 service-layer foundation is complete.

Phase 2 memory and trace convergence is complete.

Phase 3 platform-core and control-plane service boundaries are closed.

Phase 4 control-panel runtime and channel boundary work is closed.

Phase 5 permissive governance architecture baseline is closed.

The observability/task-event route is closed.

Feishu `route_callback` fallback has been removed.

## Architecture Boundary

services do the work.

rule/core layers own rules and decisions.

panel/API/channel remain adapters.

TaskEventService owns stored task timeline events.

TaskTimelineService owns read-side timeline DTO assembly.

TaskReplayService owns the service-level replay DTO boundary.

The panel `task_replay` handler calls TaskReplayService and returns the service DTO.

stream_snapshot remains in-process backlog only.

live SSE listener queues are not persisted or restored.

CPE remains permissive and emits `content_inspection=false`.

AgentShield remains permissive and emits `behavior_inspection=false`.

## Explicit Non-Goals

- no customer-content inspection;
- no CPE or AgentShield enforcement;
- no self-evolution work;
- no TemplateMarket work;
- no API replay endpoint;
- no channel replay adapter;
- no observability UI;
- no stream runtime replay;
- no live SSE listener queue persistence or restoration;
- no new Feishu fallback behavior;
- no legacy `route_callback` expansion.

## Future Work

Future packages require separate implementation plans.

Possible future product packages include:

- API replay endpoint;
- channel replay adapter;
- observability UI;
- governance enforcement;
- customer-content inspection, only if explicitly approved later;
- self-evolution or TemplateMarket, only if explicitly brought back into scope.

Each future package must keep services responsible for work, rule/core layers responsible for rules, and panel/API/channel as adapters.

## Verification Gate

Final closeout is guarded by architecture final closeout tests, phase closure tests, observability/task-event closeout tests, Feishu fallback deletion tests, panel architecture tests, router/panel regression, and full pytest.
```

- [ ] **Step 2: Update recent next directions**

In `docs/observability/task-event-closeout-status.md`, replace the `## Next Direction` body with:

```markdown
Overall architecture final closeout is tracked in `docs/architecture/final-closeout-status.md`.

Future API replay endpoint, channel replay adapter, observability UI, stream runtime replay, governance enforcement, and customer-content inspection require separate packages.

Each future package must keep services responsible for work and panel/API/channel as adapters.
```

In `docs/phase4/feishu-route-callback-deletion-readiness.md`, replace the `## Next Direction` body with:

```markdown
Overall architecture final closeout is tracked in `docs/architecture/final-closeout-status.md`.

Future Feishu work should use the standard `message_callback` / `ChannelMessage` path and keep panel/startup as adapters.
```

In `docs/phase5/phase-5-closure-status.md`, replace the `## Next Direction` body with:

```markdown
Overall architecture final closeout is tracked in `docs/architecture/final-closeout-status.md`.

Future governance enforcement, customer-content inspection, self-evolution, and TemplateMarket work require separate product decisions and implementation plans.
```

- [ ] **Step 3: Run GREEN**

Run:

```bash
pytest tests/test_architecture_final_closeout_audit.py -q
```

Expected: PASS.

### Task 3: Regression Verification and Commit

**Files:**
- Test only.

- [ ] **Step 1: Run focused and architecture suites**

Run:

```bash
pytest tests/test_architecture_final_closeout_audit.py tests/test_task_event_closeout_audit.py tests/test_feishu_route_callback_deletion_readiness.py tests/test_phase5_closure_audit.py -q
```

Expected: PASS.

- [ ] **Step 2: Run observability/service regression**

Run:

```bash
pytest tests/test_architecture_final_closeout_audit.py tests/test_task_event_closeout_audit.py tests/test_task_event_replay_readiness.py tests/test_task_replay_adapter_readiness.py tests/test_task_replay_service.py tests/test_task_timeline_service.py tests/test_task_event_service.py -q
```

Expected: PASS.

- [ ] **Step 3: Run panel/architecture regression**

Run:

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase5_closure_audit.py tests/test_phase4_closure_audit.py tests/test_architecture_final_closeout_audit.py -q
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
git add tests/test_architecture_final_closeout_audit.py docs/architecture/final-closeout-status.md docs/observability/task-event-closeout-status.md docs/phase4/feishu-route-callback-deletion-readiness.md docs/phase5/phase-5-closure-status.md docs/superpowers/plans/2026-05-28-architecture-final-closeout-audit.md
git commit -m "docs: add architecture final closeout audit"
```

Expected: commit succeeds.

## Self-Review

- Spec coverage: this plan covers final closeout documentation, source links, phase/task-event/Feishu boundary markers, deferred work, verification, and commit.
- Placeholder scan: no TBD, TODO, or open implementation placeholders.
- Scope check: no production code, API/channel replay, observability UI, stream runtime replay, live SSE queue persistence, governance enforcement, customer-content inspection, self-evolution, TemplateMarket, or legacy fallback expansion is included.
