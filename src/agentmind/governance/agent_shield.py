from __future__ import annotations

from agentmind.governance.types import (
    AgentShieldRequest,
    GovernanceDecision,
    GovernanceDecisionStatus,
)


class AgentShield:
    """Agent behavior permission decision boundary.

    Phase 5 keeps this boundary permissive by default. Future policy packages
    can add explicit behavior rules without changing service callers.
    """

    def evaluate(self, request: AgentShieldRequest) -> GovernanceDecision:
        return GovernanceDecision(
            status=GovernanceDecisionStatus.ALLOW,
            reason="no governance policy configured",
            risk_level="low",
            audit_payload=self._audit_payload(request),
        )

    def _audit_payload(self, request: AgentShieldRequest) -> dict:
        return {
            "component": "AgentShield",
            "trace_id": request.trace_id,
            "user_id": request.user_id,
            "agent_id": request.agent_id,
            "action": request.action,
            "target": request.target,
            "behavior_inspection": False,
            "policy": "permissive-no-behavior-inspection",
        }
