from dataclasses import dataclass, field


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
    security_flagged: bool = False
    is_retry: bool = False


@dataclass
class RoutingDecision:
    agent_id: str
    strategy: str = ""
    confidence: float = 0.0
    fallback_chain: list[str] = field(default_factory=list)
    reply_text: str = ""
    context: RoutingContext | None = None
