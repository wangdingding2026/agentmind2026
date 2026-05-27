from __future__ import annotations

import re

from agentmind.governance.types import (
    CPERequest,
    GovernanceDecision,
    GovernanceDecisionStatus,
)


_SENSITIVE_RE = re.compile(
    r'(sk-[a-zA-Z0-9]{20,}|api_key\s*=\s*["\'][^"\']+|password\s*=\s*["\'][^"\']+)',
    re.IGNORECASE,
)


class CPE:
    """Context Policy Engine decision boundary."""

    def evaluate(self, request: CPERequest) -> GovernanceDecision:
        sensitive_context = self._has_sensitive_context(request)
        if sensitive_context and request.agent_security_level in {"cloud", "third_party"}:
            return GovernanceDecision(
                status=GovernanceDecisionStatus.REQUIRE_APPROVAL,
                reason="sensitive context requires approval for non-local agent",
                risk_level="high",
                audit_payload=self._audit_payload(
                    request,
                    sensitive_context=sensitive_context,
                    policy="sensitive-context-non-local-agent",
                ),
            )

        return GovernanceDecision(
            status=GovernanceDecisionStatus.ALLOW,
            reason="no CPE policy matched",
            risk_level="low",
            audit_payload=self._audit_payload(
                request,
                sensitive_context=sensitive_context,
                policy="default-allow",
            ),
        )

    def _has_sensitive_context(self, request: CPERequest) -> bool:
        message = str(request.context.get("message", ""))
        return bool(_SENSITIVE_RE.search(message))

    def _audit_payload(
        self,
        request: CPERequest,
        *,
        sensitive_context: bool,
        policy: str,
    ) -> dict:
        return {
            "component": "CPE",
            "trace_id": request.trace_id,
            "user_id": request.user_id,
            "agent_id": request.agent_id,
            "agent_security_level": request.agent_security_level,
            "memory_count": len(request.memory_items),
            "sensitive_context": sensitive_context,
            "policy": policy,
        }
