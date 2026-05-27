from __future__ import annotations

import json
from typing import Any

from agentmind.services.audit_service import AuditService
from agentmind.services.trace_service import TraceService


class RoutingExplanationService:
    """Aggregate routing explanation data for the control plane."""

    def __init__(
        self,
        *,
        trace_service=None,
        audit_service=None,
        capability_registry=None,
        strategy_manager=None,
    ):
        self._trace_service = trace_service or TraceService()
        self._audit_service = audit_service or AuditService()
        self._capability_registry = capability_registry
        self._strategy_manager = strategy_manager

    async def explain(self, trace_id: str) -> dict[str, Any]:
        trace = await self._trace_service.get_trace(trace_id)
        if trace is None:
            return self._missing(trace_id)

        decision = self._decision_from_trace(trace)
        selected_agent = self._selected_agent(decision.get("agent_id", ""))
        return {
            "trace_id": trace_id,
            "found": True,
            "summary": trace.get("summary", ""),
            "decision": decision,
            "selected_agent": selected_agent,
            "strategies": self._strategies(),
            "audit_events": await self._audit_events(trace_id),
        }

    def _missing(self, trace_id: str) -> dict[str, Any]:
        return {
            "trace_id": trace_id,
            "found": False,
            "summary": "Trace not found",
            "decision": {},
            "selected_agent": None,
            "strategies": [],
            "audit_events": [],
        }

    def _decision_from_trace(self, trace: dict[str, Any]) -> dict[str, Any]:
        content = self._json_dict(trace.get("content"))
        return {
            "agent_id": content.get("agent_id", trace.get("agent_id", "")),
            "strategy": content.get("strategy", trace.get("strategy", "")),
            "confidence": content.get("confidence", trace.get("confidence", 0.0)),
            "fallback_chain": content.get(
                "fallback_chain",
                self._json_list(trace.get("fallback_chain")),
            ),
            "security_flagged": bool(
                content.get("security_flagged", trace.get("security_flagged", False))
            ),
            "raw_message": content.get("raw_message", trace.get("raw_message", "")),
            "candidates": content.get("candidates", self._json_list(trace.get("candidates"))),
        }

    def _selected_agent(self, agent_id: str) -> dict[str, Any] | None:
        if not agent_id or self._capability_registry is None:
            return None
        return self._capability_registry.get_profile(agent_id)

    def _strategies(self) -> list[dict[str, Any]]:
        if self._strategy_manager is None:
            return []
        return self._strategy_manager.list_strategies()

    async def _audit_events(self, trace_id: str) -> list[dict[str, Any]]:
        return await self._audit_service.query_events(trace_id=trace_id, limit=20)

    def _json_dict(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _json_list(self, value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []
        return parsed if isinstance(parsed, list) else []
