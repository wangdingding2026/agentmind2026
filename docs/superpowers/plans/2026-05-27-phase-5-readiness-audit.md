# Phase 5 Readiness Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Phase 5 readiness gate that lets AgentMind move from closed Phase 4 runtime/channel work into security-governance planning without starting CPE or AgentShield implementation.

**Architecture:** This package is documentation plus architecture audit tests. Phase 4 remains closed, Phase 5 readiness records the next entry criteria, and existing services stay unchanged: `ChannelHub` owns channel lifecycle and Feishu glue, `SessionRuntimeService` owns panel-facing runtime controls, and panel/API/channel handlers remain adapters.

**Tech Stack:** Markdown architecture docs, Python `pathlib` audit tests, pytest.

---

## Scope

This package creates:

- `docs/phase5/phase-5-readiness.md`
- `tests/test_phase5_readiness_audit.py`

It modifies:

- `docs/phase4/phase-4-closure-status.md`

It does not modify runtime code.

## Non-Goals

- Do not implement CPE.
- Do not implement AgentShield.
- Do not implement persistent task-event replay.
- Do not delete `feishu.route_callback`.
- Do not change API/Webhook channel behavior.
- Do not expand old fallback business logic.

## Task 1: RED Phase 5 Readiness Audit

**Files:**
- Create: `tests/test_phase5_readiness_audit.py`

- [ ] **Step 1: Write the failing audit test**

Create `tests/test_phase5_readiness_audit.py`:

```python
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE5_DOC = PROJECT_ROOT / "docs" / "phase5" / "phase-5-readiness.md"
PHASE4_DOC = PROJECT_ROOT / "docs" / "phase4" / "phase-4-closure-status.md"


REQUIRED_PHASE5_MARKERS = {
    "Phase 5 readiness",
    "security governance readiness",
    "docs/phase4/phase-4-closure-status.md",
    "Phase 4 is closed",
    "service/rule/channel boundaries",
    "services do the work",
    "rule/core layers own rules",
    "panel/API/channel remain adapters",
    "CPE",
    "AgentShield",
    "do not implement CPE",
    "do not implement AgentShield",
    "persistent task-event replay",
    "observability/task-event",
    "feishu.route_callback",
    "bounded migration fallback",
    "delete criteria",
    "ChannelMessage",
}


def _phase5_text() -> str:
    assert PHASE5_DOC.exists(), "docs/phase5/phase-5-readiness.md is required"
    return PHASE5_DOC.read_text(encoding="utf-8")


def test_phase5_readiness_document_exists_and_names_phase4_source():
    text = _phase5_text()

    assert "Phase 5 readiness" in text
    assert "docs/phase4/phase-4-closure-status.md" in text
    assert "Phase 4 is closed" in text


def test_phase5_readiness_document_names_required_boundaries_and_non_goals():
    text = _phase5_text()
    missing = sorted(marker for marker in REQUIRED_PHASE5_MARKERS if marker not in text)

    assert missing == []


def test_phase5_readiness_document_orders_work_before_security_implementation():
    text = _phase5_text()

    readiness = text.index("Phase 5 readiness")
    cpe_start = text.index("CPE start criteria")
    agent_shield_start = text.index("AgentShield start criteria")

    assert readiness < cpe_start < agent_shield_start
    assert "CPE implementation package" not in text
    assert "AgentShield implementation package" not in text


def test_phase4_closure_points_to_phase5_readiness_document():
    text = PHASE4_DOC.read_text(encoding="utf-8")

    assert "docs/phase5/phase-5-readiness.md" in text
    assert "Start Phase 5 readiness" in text
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_phase5_readiness_audit.py -q
```

Expected: FAIL because `docs/phase5/phase-5-readiness.md` does not exist and Phase 4 closure does not yet point to it.

## Task 2: GREEN Phase 5 Readiness Document

**Files:**
- Create: `docs/phase5/phase-5-readiness.md`
- Modify: `docs/phase4/phase-4-closure-status.md`

- [ ] **Step 1: Add `docs/phase5/phase-5-readiness.md`**

Create a document with these sections:

```markdown
# Phase 5 Readiness

## Readiness Decision

Phase 5 readiness is the security governance readiness gate after Phase 4 closure.

...
```

The document must state:

- Phase 4 is closed and the entry source is `docs/phase4/phase-4-closure-status.md`.
- Phase 5 readiness comes before CPE or AgentShield implementation.
- CPE start criteria require service/rule/channel boundaries to be confirmed.
- AgentShield start criteria require execution and approval boundaries to be identified.
- persistent task-event replay stays deferred to an observability/task-event package.
- `feishu.route_callback` is a bounded migration fallback with delete criteria.

- [ ] **Step 2: Update Phase 4 closure next direction**

In `docs/phase4/phase-4-closure-status.md`, update `## Next Direction` to point at:

```markdown
Start Phase 5 readiness in `docs/phase5/phase-5-readiness.md` only after this closure audit remains green.
```

- [ ] **Step 3: Run GREEN focused audit**

Run:

```bash
pytest tests/test_phase5_readiness_audit.py -q
```

Expected: PASS.

## Task 3: Regression Verification

**Files:**
- Test only.

- [ ] **Step 1: Run focused closure/readiness tests**

```bash
pytest tests/test_phase5_readiness_audit.py tests/test_phase4_closure_audit.py tests/test_phase3_closure_audit.py -q
```

Expected: PASS.

- [ ] **Step 2: Run panel/architecture regression**

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py tests/test_phase4_closure_audit.py tests/test_phase5_readiness_audit.py -q
```

Expected: PASS.

- [ ] **Step 3: Run channel/runtime regression**

```bash
pytest tests/test_startup.py tests/test_channel_hub.py tests/test_feishu_channel.py tests/test_feishu_path.py tests/test_session_runtime_service.py tests/test_stream.py -q
```

Expected: PASS.

- [ ] **Step 4: Run router/panel regression**

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full verification**

```bash
pytest -q
git diff --check
git status --short
```

Expected: pytest passes, diff check is clean, and status only shows this package before commit.

## Task 4: Commit

**Files:**
- `docs/superpowers/plans/2026-05-27-phase-5-readiness-audit.md`
- `docs/phase5/phase-5-readiness.md`
- `docs/phase4/phase-4-closure-status.md`
- `tests/test_phase5_readiness_audit.py`

- [ ] **Step 1: Commit**

```bash
git add docs/superpowers/plans/2026-05-27-phase-5-readiness-audit.md docs/phase5/phase-5-readiness.md docs/phase4/phase-4-closure-status.md tests/test_phase5_readiness_audit.py
git commit -m "docs: add phase 5 readiness gate"
```

## Self-Review

- Spec coverage: Covers Phase 5 readiness only; it does not start CPE, AgentShield, persistent task-event replay, API/Webhook channel, or fallback deletion work.
- Placeholder scan: No placeholders.
- Type consistency: File names and markers match the planned test and docs.
