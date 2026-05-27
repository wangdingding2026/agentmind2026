from __future__ import annotations

from agentmind.governance.types import (
    AgentShieldRequest,
    GovernanceDecision,
    GovernanceDecisionStatus,
)


class AgentShield:
    """Agent behavior permission decision boundary.

    This skeleton defines the contract only. Runtime interception is
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
