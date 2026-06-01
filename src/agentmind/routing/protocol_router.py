from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class ProtocolRoute:
    kind: str
    value: str = ""
    data: dict = field(default_factory=dict)


class ProtocolRouter:
    """Deterministic protocol command router.

    This layer only recognizes explicit command syntax. It must not classify
    natural-language semantic requests.
    """

    def __init__(
        self,
        *,
        agent_registry=None,
        orchestration_matcher: Callable[[str], dict | None] | None = None,
    ):
        self._agent_registry = agent_registry
        self._orchestration_matcher = orchestration_matcher

    def match(
        self,
        message: str,
        *,
        session_id: str = "",
        attach_registry=None,
    ) -> ProtocolRoute | None:
        text = message.strip()
        if not text:
            return None

        if self._is_new_session(text):
            return ProtocolRoute(kind="new_session")

        orchestration = self._match_orchestration(text)
        if orchestration is not None:
            return orchestration

        attached = self._match_attached_session(session_id, attach_registry)
        if attached is not None:
            return attached

        expand = self._match_result_set_expand(text)
        if expand is not None:
            return expand

        explicit = self._match_explicit_agent(text)
        if explicit is not None:
            return explicit

        security = self._match_security_intercept(text)
        if security is not None:
            return security

        return None

    def _is_new_session(self, text: str) -> bool:
        text = re.sub(r"@\S+\s*", "", text).strip()
        if not text.startswith("/new"):
            return False
        if len(text) == 4:
            return True
        ch = text[4]
        return ch.isspace() or ord(ch) > 127

    def _match_attached_session(self, session_id: str, attach_registry) -> ProtocolRoute | None:
        if not session_id or attach_registry is None:
            return None
        bound_trace_id = attach_registry.get_bound_task(session_id)
        if not bound_trace_id:
            return None
        return ProtocolRoute(
            kind="attach_session",
            value=bound_trace_id,
            data={"session_id": session_id},
        )

    def _match_result_set_expand(self, text: str) -> ProtocolRoute | None:
        match = re.search(r"^展开\s*第\s*(\d+)\s*(条|个)?\s*$", text)
        if not match:
            return None
        return ProtocolRoute(kind="result_set_expand", value=match.group(1))

    def _match_orchestration(self, text: str) -> ProtocolRoute | None:
        if self._orchestration_matcher is None:
            return None
        plan = self._orchestration_matcher(text)
        if not plan:
            return None
        return ProtocolRoute(kind="orchestration", data={"plan": plan})

    def _match_explicit_agent(self, text: str) -> ProtocolRoute | None:
        match = re.match(r"^@(\S+)", text)
        if not match:
            return None
        raw_agent = match.group(1)
        if _looks_like_multi_agent_discussion(text):
            return None
        agent_id = raw_agent
        if self._agent_registry is not None:
            from agentmind.routing.strategies.explicit_directive import ExplicitDirective

            resolved = ExplicitDirective(self._agent_registry)._resolve(raw_agent)
            if not resolved:
                return None
            agent_id = resolved
        return ProtocolRoute(kind="explicit_agent", value=agent_id)

    def _match_security_intercept(self, text: str) -> ProtocolRoute | None:
        if not _contains_sensitive_text(text) or self._agent_registry is None:
            return None
        local_agents = self._agent_registry.get_healthy_agents_by_security_level("local")
        if not local_agents:
            return None
        return ProtocolRoute(kind="security_intercept", value=local_agents[0])


def _looks_like_multi_agent_discussion(text: str) -> bool:
    mentions = re.findall(r"@(\S+)", text)
    return len(mentions) >= 2 and bool(re.search(r"讨论|辩论|聊聊|说说", text))


def _contains_sensitive_text(text: str) -> bool:
    return bool(
        re.search(
            r'(sk-[a-zA-Z0-9]{20,}|api_key\s*=\s*["\'][^"\']+|password\s*=\s*["\'][^"\']+)',
            text,
            re.IGNORECASE,
        )
    )
