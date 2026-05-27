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
