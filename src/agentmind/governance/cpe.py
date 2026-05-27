from __future__ import annotations

from agentmind.governance.types import (
    CPERequest,
    GovernanceDecision,
    GovernanceDecisionStatus,
)


class CPE:
    """Context Policy Engine decision boundary.

    Phase 5 keeps this boundary permissive by default. Future policy packages
    can add explicit inspection rules without changing service callers.
    """

    def evaluate(self, request: CPERequest) -> GovernanceDecision:
        return GovernanceDecision(
            status=GovernanceDecisionStatus.ALLOW,
            reason="no CPE policy configured",
            risk_level="low",
            audit_payload=self._audit_payload(request),
        )

    def _audit_payload(self, request: CPERequest) -> dict:
        return {
            "component": "CPE",
            "trace_id": request.trace_id,
            "user_id": request.user_id,
            "agent_id": request.agent_id,
            "agent_security_level": request.agent_security_level,
            "memory_count": len(request.memory_items),
            "content_inspection": False,
            "policy": "permissive-no-content-inspection",
        }
