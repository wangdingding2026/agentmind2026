from dataclasses import dataclass
from enum import StrEnum


class SemanticIntentType(StrEnum):
    CONVERSATION_HISTORY = "conversation_history"
    AGENT_TASK = "agent_task"
    AGENTMIND_CAPABILITY = "agentmind_capability"
    SMALLTALK = "smalltalk"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SemanticIntent:
    intent: SemanticIntentType = SemanticIntentType.UNKNOWN
    confidence: float = 0.0
    target_agent: str = ""
    time_scope: str = "none"
    current_session: bool = False
    explicit_date: str = ""
    agent_filter: str = ""
    requested_format: str = "answer_only"
    reason: str = ""

    @classmethod
    def from_llm_payload(cls, payload: dict) -> "SemanticIntent":
        if not isinstance(payload, dict):
            return cls()
        try:
            intent_type = SemanticIntentType(str(payload.get("intent", "unknown") or "unknown"))
        except ValueError:
            return cls()

        confidence = _safe_confidence(payload.get("confidence"), 0.0)
        if intent_type == SemanticIntentType.UNKNOWN:
            confidence = 0.0

        return cls(
            intent=intent_type,
            confidence=confidence,
            target_agent=str(payload.get("target_agent") or ""),
            time_scope=str(payload.get("time_scope") or "none"),
            current_session=bool(payload.get("current_session")),
            explicit_date=str(payload.get("explicit_date") or ""),
            agent_filter=str(payload.get("agent_filter") or ""),
            requested_format=str(payload.get("requested_format") or "answer_only"),
            reason=str(payload.get("reason") or ""),
        )


def _safe_confidence(value, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return min(1.0, max(0.0, parsed))
