# Phase 5 Closure Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Phase 5 by documenting and testing the permissive governance architecture baseline before Phase 6 readiness begins.

**Architecture:** Phase 5 closes with CPE and AgentShield rule/core boundaries present, but permissive by default. Services may keep governance seams and dry-run metadata, while panel/API/channel adapters and executors do not own or enforce governance rules.

**Tech Stack:** Markdown architecture docs, pytest architecture audit tests, existing governance skeleton tests.

---

## Scope

Create:

- `docs/phase5/phase-5-closure-status.md`
- `tests/test_phase5_closure_audit.py`
- `docs/superpowers/plans/2026-05-27-phase-5-closure-audit.md`

Modify:

- `docs/phase5/phase-5-readiness.md`

Do not modify:

- CPE behavior
- AgentShield behavior
- RoutingService behavior
- executor behavior
- panel/API/channel adapters
- persistent task-event replay
- Phase 6 implementation code

## Closure Requirements

The Phase 5 closure document must state:

- Phase 5 is closed.
- Phase 5 closes as a permissive governance architecture baseline.
- CPE remains permissive and does not inspect customer message content.
- CPE emits `content_inspection=false`.
- AgentShield remains permissive and does not inspect behavior payloads.
- AgentShield emits `behavior_inspection=false`.
- RoutingService CPE integration remains dry-run and does not block, reroute, or require approval.
- AuditService keeps governance event shape and future status mapping.
- panel/API/channel remain adapters and do not own governance rules.
- `feishu.route_callback` remains a bounded migration fallback.
- persistent task-event replay remains deferred.
- Phase 6 readiness is next and Phase 6 implementation has not started.

## Task 1: RED Closure Audit Tests

**Files:**

- Create: `tests/test_phase5_closure_audit.py`

- [ ] **Step 1: Add closure audit test file**

Create:

```python
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE5_CLOSURE_DOC = PROJECT_ROOT / "docs" / "phase5" / "phase-5-closure-status.md"
PHASE5_READINESS_DOC = PROJECT_ROOT / "docs" / "phase5" / "phase-5-readiness.md"


REQUIRED_PHASE5_CLOSURE_MARKERS = {
    "Phase 5 is closed",
    "permissive governance architecture baseline",
    "CPE",
    "does not inspect customer message content",
    "content_inspection=false",
    "AgentShield",
    "does not inspect behavior payloads",
    "behavior_inspection=false",
    "RoutingService",
    "dry-run",
    "does not block, reroute, or require approval",
    "AuditService",
    "governance event shape",
    "future status mapping",
    "panel/API/channel remain adapters",
    "do not own governance rules",
    "feishu.route_callback",
    "bounded migration fallback",
    "persistent task-event replay",
    "observability/task-event",
    "Phase 6 readiness",
    "Phase 6 implementation has not started",
}


def _phase5_closure_text() -> str:
    assert PHASE5_CLOSURE_DOC.exists(), (
        "docs/phase5/phase-5-closure-status.md is required"
    )
    return PHASE5_CLOSURE_DOC.read_text(encoding="utf-8")


def test_phase5_closure_document_exists_and_declares_closed():
    text = _phase5_closure_text()

    assert "Phase 5 is closed" in text
    assert "permissive governance architecture baseline" in text


def test_phase5_closure_document_names_required_boundaries():
    text = _phase5_closure_text()
    missing = sorted(marker for marker in REQUIRED_PHASE5_CLOSURE_MARKERS if marker not in text)

    assert missing == []


def test_phase5_readiness_points_to_phase5_closure_and_phase6_readiness():
    text = PHASE5_READINESS_DOC.read_text(encoding="utf-8")

    assert "docs/phase5/phase-5-closure-status.md" in text
    assert "Phase 6 readiness" in text
```

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_phase5_closure_audit.py -q
```

Expected: FAIL because `docs/phase5/phase-5-closure-status.md` does not exist and readiness does not yet point to it.

## Task 2: GREEN Closure Document

**Files:**

- Create: `docs/phase5/phase-5-closure-status.md`
- Modify: `docs/phase5/phase-5-readiness.md`

- [ ] **Step 1: Add Phase 5 closure status**

Create the closure document with sections:

```markdown
# Phase 5 Closure Status

## Closure Decision

Phase 5 is closed as a permissive governance architecture baseline.

...
```

Include every marker listed in `REQUIRED_PHASE5_CLOSURE_MARKERS`.

- [ ] **Step 2: Update readiness next direction**

Change `docs/phase5/phase-5-readiness.md` `## Next Direction` to point to:

```markdown
Phase 5 closure is recorded in `docs/phase5/phase-5-closure-status.md`.

Next, start Phase 6 readiness only. Phase 6 implementation has not started.
```

- [ ] **Step 3: Run GREEN focused tests**

```bash
pytest tests/test_phase5_closure_audit.py tests/test_phase5_readiness_audit.py -q
```

Expected: PASS.

## Task 3: Regression Verification

**Files:**

- No additional edits expected.

- [ ] **Step 1: Run governance and closure focused suites**

```bash
pytest tests/test_governance_skeleton.py tests/test_cpe_routing_entrypoint.py tests/test_audit_service.py tests/test_phase5_readiness_audit.py tests/test_phase5_closure_audit.py -q
```

- [ ] **Step 2: Run architecture/panel closure suites**

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py tests/test_phase4_closure_audit.py tests/test_phase5_readiness_audit.py tests/test_phase5_closure_audit.py -q
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
git add docs/phase5/phase-5-closure-status.md docs/phase5/phase-5-readiness.md tests/test_phase5_closure_audit.py docs/superpowers/plans/2026-05-27-phase-5-closure-audit.md
git commit -m "docs: close phase 5 permissive governance"
```
