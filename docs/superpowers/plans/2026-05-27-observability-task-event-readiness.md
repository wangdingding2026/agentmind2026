# Observability Task Event Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define the task-event observability boundary before adding persistent task-event storage or replay.

**Architecture:** TaskService owns task lifecycle state, TraceService owns routing trace explanation, AuditService owns audit/security/config events, and the future TaskEventService should own ordered execution timeline events. Panel/API/channel remain adapters and must not assemble task-event timelines themselves.

**Tech Stack:** Markdown architecture docs, pytest architecture audit tests, existing service boundary docs.

---

## Scope

Create:

- `docs/observability/task-event-readiness.md`
- `tests/test_observability_task_event_readiness.py`
- `docs/superpowers/plans/2026-05-27-observability-task-event-readiness.md`

Do not modify:

- task storage schema
- stream runtime behavior
- panel/API/channel adapters
- routing behavior
- CPE/AgentShield behavior
- persistent task-event replay
- observability UI

## Readiness Requirements

The readiness document must state:

- task-event observability readiness;
- persistent task-event replay is the target later package, not this package;
- TaskService owns task lifecycle state;
- TraceService owns routing traces and routing explanation source data;
- AuditService owns audit events and governance/config/security records;
- future TaskEventService owns ordered task timeline events;
- event types include `task_started`, `routing_started`, `agent_selected`, `execution_started`, `partial_output`, `completed`, and `failed`;
- stream_snapshot remains in-process backlog only;
- live SSE listener queues are not persisted or restored;
- panel/API/channel remain adapters;
- no observability UI in this package;
- no CPE or AgentShield enforcement;
- no EvolutionEngine;
- no TemplateMarket.

## Task 1: RED Readiness Audit Tests

**Files:**

- Create: `tests/test_observability_task_event_readiness.py`

- [ ] **Step 1: Add readiness audit tests**

Create:

```python
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
READINESS_DOC = PROJECT_ROOT / "docs" / "observability" / "task-event-readiness.md"
PHASE5_CLOSURE_DOC = PROJECT_ROOT / "docs" / "phase5" / "phase-5-closure-status.md"


REQUIRED_TASK_EVENT_READINESS_MARKERS = {
    "task-event observability readiness",
    "persistent task-event replay",
    "later package",
    "TaskService owns task lifecycle state",
    "TraceService owns routing traces",
    "AuditService owns audit events",
    "TaskEventService owns ordered task timeline events",
    "task_started",
    "routing_started",
    "agent_selected",
    "execution_started",
    "partial_output",
    "completed",
    "failed",
    "stream_snapshot remains in-process backlog only",
    "live SSE listener queues are not persisted or restored",
    "panel/API/channel remain adapters",
    "no observability UI",
    "no CPE or AgentShield enforcement",
    "no EvolutionEngine",
    "no TemplateMarket",
}


def _readiness_text() -> str:
    assert READINESS_DOC.exists(), (
        "docs/observability/task-event-readiness.md is required"
    )
    return READINESS_DOC.read_text(encoding="utf-8")


def test_task_event_readiness_document_exists_and_defers_replay():
    text = _readiness_text()

    assert "task-event observability readiness" in text
    assert "persistent task-event replay" in text
    assert "later package" in text


def test_task_event_readiness_document_names_required_boundaries():
    text = _readiness_text()
    missing = sorted(
        marker for marker in REQUIRED_TASK_EVENT_READINESS_MARKERS if marker not in text
    )

    assert missing == []


def test_phase5_closure_points_to_task_event_readiness():
    text = PHASE5_CLOSURE_DOC.read_text(encoding="utf-8")

    assert "docs/observability/task-event-readiness.md" in text
```

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_observability_task_event_readiness.py -q
```

Expected: FAIL because the readiness document does not exist and Phase 5 closure does not point to it.

## Task 2: GREEN Readiness Document

**Files:**

- Create: `docs/observability/task-event-readiness.md`
- Modify: `docs/phase5/phase-5-closure-status.md`

- [ ] **Step 1: Add readiness document**

Create a document that includes every marker in `REQUIRED_TASK_EVENT_READINESS_MARKERS`.

- [ ] **Step 2: Update Phase 5 closure next direction**

Add `docs/observability/task-event-readiness.md` as the next architecture package after Phase 5 closure.

- [ ] **Step 3: Run GREEN focused tests**

```bash
pytest tests/test_observability_task_event_readiness.py tests/test_phase5_closure_audit.py -q
```

Expected: PASS.

## Task 3: Regression Verification

**Files:**

- No additional edits expected.

- [ ] **Step 1: Run focused observability and closure tests**

```bash
pytest tests/test_observability_task_event_readiness.py tests/test_phase5_closure_audit.py tests/test_phase4_closure_audit.py -q
```

- [ ] **Step 2: Run governance/readiness regression**

```bash
pytest tests/test_governance_skeleton.py tests/test_cpe_routing_entrypoint.py tests/test_audit_service.py tests/test_phase5_readiness_audit.py tests/test_phase5_closure_audit.py tests/test_observability_task_event_readiness.py -q
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
git add docs/observability/task-event-readiness.md docs/phase5/phase-5-closure-status.md tests/test_observability_task_event_readiness.py docs/superpowers/plans/2026-05-27-observability-task-event-readiness.md
git commit -m "docs: add task event observability readiness"
```
