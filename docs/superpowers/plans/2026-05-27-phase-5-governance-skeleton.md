# Phase 5 Governance Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first Phase 5 governance package with CPE and AgentShield decision types and service entry points, without changing runtime routing, memory retrieval, channel, or executor behavior.

**Architecture:** `agentmind.governance` becomes the rule/core home for security-governance decisions. Services will later call these boundaries, but this package only defines data contracts and default allow behavior so future CPE and AgentShield work has a stable target. Panel/API/channel handlers remain adapters and do not import governance internals.

**Tech Stack:** Python dataclasses, enum types, pytest architecture/unit tests, existing AgentMind package layout.

---

## Scope

Create:

- `src/agentmind/governance/__init__.py`
- `src/agentmind/governance/types.py`
- `src/agentmind/governance/cpe.py`
- `src/agentmind/governance/agent_shield.py`
- `tests/test_governance_skeleton.py`

Modify:

- `docs/phase5/phase-5-readiness.md`

Do not modify runtime routing, memory retrieval, executor, panel, channel, or fallback code.

## Non-Goals

- Do not route sensitive messages through CPE yet.
- Do not gate private memory retrieval yet.
- Do not intercept tools, commands, ProtocolGateway, or executors yet.
- Do not add approval workflows.
- Do not write AuditService events yet.
- Do not delete or extend `feishu.route_callback`.

## Task 1: RED Governance Skeleton Tests

**Files:**
- Create: `tests/test_governance_skeleton.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_governance_skeleton.py`:

```python
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOVERNANCE_DIR = PROJECT_ROOT / "src" / "agentmind" / "governance"
PANEL_SERVER = PROJECT_ROOT / "src" / "agentmind" / "panel" / "server.py"
CHANNELS_DIR = PROJECT_ROOT / "src" / "agentmind" / "channels"
ROUTER_SERVICE = PROJECT_ROOT / "src" / "agentmind" / "services" / "routing_service.py"
MEMORY_SERVICE = PROJECT_ROOT / "src" / "agentmind" / "memory" / "service.py"


def test_governance_package_files_exist():
    expected = {
        "__init__.py",
        "types.py",
        "cpe.py",
        "agent_shield.py",
    }
    missing = sorted(name for name in expected if not (GOVERNANCE_DIR / name).exists())

    assert missing == []


def test_cpe_default_decision_contract_allows_without_runtime_policy():
    from agentmind.governance import (
        CPE,
        CPERequest,
        GovernanceDecision,
        GovernanceDecisionStatus,
    )

    decision = CPE().evaluate(
        CPERequest(
            trace_id="t1",
            user_id="u1",
            agent_id="a1",
            agent_security_level="local",
            context={"message": "hello"},
            memory_items=[{"memory_id": "m1", "access_level": "public"}],
        )
    )

    assert isinstance(decision, GovernanceDecision)
    assert decision.status == GovernanceDecisionStatus.ALLOW
    assert decision.risk_level == "low"
    assert decision.reason == "no governance policy configured"
    assert decision.audit_payload["component"] == "CPE"
    assert decision.audit_payload["trace_id"] == "t1"


def test_agent_shield_default_decision_contract_allows_without_runtime_policy():
    from agentmind.governance import (
        AgentShield,
        AgentShieldRequest,
        GovernanceDecision,
        GovernanceDecisionStatus,
    )

    decision = AgentShield().evaluate(
        AgentShieldRequest(
            trace_id="t2",
            user_id="u1",
            agent_id="a1",
            action="execute",
            target="local-agent",
            payload={"instruction": "summarize"},
        )
    )

    assert isinstance(decision, GovernanceDecision)
    assert decision.status == GovernanceDecisionStatus.ALLOW
    assert decision.risk_level == "low"
    assert decision.reason == "no governance policy configured"
    assert decision.audit_payload["component"] == "AgentShield"
    assert decision.audit_payload["action"] == "execute"


def test_governance_skeleton_is_not_wired_into_runtime_adapters_or_services_yet():
    checked_paths = [
        PANEL_SERVER,
        ROUTER_SERVICE,
        MEMORY_SERVICE,
        *CHANNELS_DIR.glob("*.py"),
    ]
    offenders = []
    for path in checked_paths:
        text = path.read_text(encoding="utf-8")
        if "agentmind.governance" in text:
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_governance_skeleton.py -q
```

Expected: FAIL because `agentmind.governance` does not exist.

## Task 2: GREEN Governance Skeleton

**Files:**
- Create: `src/agentmind/governance/__init__.py`
- Create: `src/agentmind/governance/types.py`
- Create: `src/agentmind/governance/cpe.py`
- Create: `src/agentmind/governance/agent_shield.py`

- [ ] **Step 1: Add shared governance types**

Create `src/agentmind/governance/types.py` with dataclasses and enum values:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GovernanceDecisionStatus(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    REQUIRE_APPROVAL = "require_approval"


@dataclass
class GovernanceDecision:
    status: GovernanceDecisionStatus
    reason: str = ""
    risk_level: str = "low"
    audit_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class CPERequest:
    trace_id: str = ""
    user_id: str = ""
    agent_id: str = ""
    agent_security_level: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    memory_items: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentShieldRequest:
    trace_id: str = ""
    user_id: str = ""
    agent_id: str = ""
    action: str = ""
    target: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 2: Add CPE boundary**

Create `src/agentmind/governance/cpe.py`:

```python
from __future__ import annotations

from agentmind.governance.types import (
    CPERequest,
    GovernanceDecision,
    GovernanceDecisionStatus,
)


class CPE:
    """Context Policy Engine boundary.

    This skeleton defines the decision contract only. Runtime policy wiring is
    intentionally deferred to later Phase 5 packages.
    """

    def evaluate(self, request: CPERequest) -> GovernanceDecision:
        return GovernanceDecision(
            status=GovernanceDecisionStatus.ALLOW,
            reason="no governance policy configured",
            risk_level="low",
            audit_payload={
                "component": "CPE",
                "trace_id": request.trace_id,
                "user_id": request.user_id,
                "agent_id": request.agent_id,
                "agent_security_level": request.agent_security_level,
                "memory_count": len(request.memory_items),
            },
        )
```

- [ ] **Step 3: Add AgentShield boundary**

Create `src/agentmind/governance/agent_shield.py`:

```python
from __future__ import annotations

from agentmind.governance.types import (
    AgentShieldRequest,
    GovernanceDecision,
    GovernanceDecisionStatus,
)


class AgentShield:
    """Agent behavior permission boundary.

    This skeleton defines the decision contract only. Runtime interception is
    intentionally deferred to later Phase 5 packages.
    """

    def evaluate(self, request: AgentShieldRequest) -> GovernanceDecision:
        return GovernanceDecision(
            status=GovernanceDecisionStatus.ALLOW,
            reason="no governance policy configured",
            risk_level="low",
            audit_payload={
                "component": "AgentShield",
                "trace_id": request.trace_id,
                "user_id": request.user_id,
                "agent_id": request.agent_id,
                "action": request.action,
                "target": request.target,
            },
        )
```

- [ ] **Step 4: Export public governance API**

Create `src/agentmind/governance/__init__.py`:

```python
from agentmind.governance.agent_shield import AgentShield
from agentmind.governance.cpe import CPE
from agentmind.governance.types import (
    AgentShieldRequest,
    CPERequest,
    GovernanceDecision,
    GovernanceDecisionStatus,
)

__all__ = [
    "AgentShield",
    "AgentShieldRequest",
    "CPE",
    "CPERequest",
    "GovernanceDecision",
    "GovernanceDecisionStatus",
]
```

- [ ] **Step 5: Run GREEN focused tests**

Run:

```bash
pytest tests/test_governance_skeleton.py -q
```

Expected: PASS.

## Task 3: Update Readiness Next Direction

**Files:**
- Modify: `docs/phase5/phase-5-readiness.md`

- [ ] **Step 1: Update next direction**

Change the final `## Next Direction` paragraph so it records that the first security-governance skeleton package defines CPE and AgentShield decision contracts only, and that later packages must still wire CPE into routing/memory and AgentShield into execution boundaries through services.

- [ ] **Step 2: Run focused tests**

Run:

```bash
pytest tests/test_governance_skeleton.py tests/test_phase5_readiness_audit.py -q
```

Expected: PASS.

## Task 4: Regression Verification

**Files:**
- Test only.

- [ ] **Step 1: Run focused governance/readiness tests**

```bash
pytest tests/test_governance_skeleton.py tests/test_phase5_readiness_audit.py tests/test_phase4_closure_audit.py tests/test_phase3_closure_audit.py -q
```

Expected: PASS.

- [ ] **Step 2: Run related module regression**

```bash
pytest tests/test_audit_service.py tests/test_config_service.py tests/test_pipeline_executors.py -q
```

Expected: PASS.

- [ ] **Step 3: Run panel/architecture regression**

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py tests/test_phase4_closure_audit.py tests/test_phase5_readiness_audit.py -q
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

## Task 5: Commit

**Files:**
- `docs/superpowers/plans/2026-05-27-phase-5-governance-skeleton.md`
- `docs/phase5/phase-5-readiness.md`
- `src/agentmind/governance/__init__.py`
- `src/agentmind/governance/types.py`
- `src/agentmind/governance/cpe.py`
- `src/agentmind/governance/agent_shield.py`
- `tests/test_governance_skeleton.py`

- [ ] **Step 1: Commit**

```bash
git add docs/superpowers/plans/2026-05-27-phase-5-governance-skeleton.md docs/phase5/phase-5-readiness.md src/agentmind/governance/__init__.py src/agentmind/governance/types.py src/agentmind/governance/cpe.py src/agentmind/governance/agent_shield.py tests/test_governance_skeleton.py
git commit -m "feat: add governance skeleton"
```

## Self-Review

- Spec coverage: Covers only CPE and AgentShield skeleton contracts.
- Placeholder scan: No placeholders.
- Type consistency: Test imports match exported names.
