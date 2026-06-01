from dataclasses import dataclass, field

from agentmind.memory.dto import MemoryContext
from agentmind.routing.semantic_intent import SemanticIntent


@dataclass
class RequestIdentity:
    trace_id: str = ""
    user_id: str = ""
    session_id: str = ""


@dataclass
class RoutingContext:
    identity: RequestIdentity
    raw_message: str
    candidates: list[str] = field(default_factory=list)
    memories: list[dict] = field(default_factory=list)
    memory_context: MemoryContext | None = None
    semantic_intent: SemanticIntent | None = None
    security_flagged: bool = False
    is_retry: bool = False


@dataclass
class RoutingDecision:
    agent_id: str
    strategy: str = ""
    confidence: float = 0.0
    fallback_chain: list[str] = field(default_factory=list)
    reply_text: str = ""
    semantic_intent: SemanticIntent | None = None
    context: RoutingContext | None = None
