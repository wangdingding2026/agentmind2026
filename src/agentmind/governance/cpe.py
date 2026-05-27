from __future__ import annotations

from agentmind.governance.types import (
    CPERequest,
    GovernanceDecision,
    GovernanceDecisionStatus,
)


class CPE:
    """Context Policy Engine decision boundary.

    This skeleton defines the contract only. Runtime policy wiring is
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
