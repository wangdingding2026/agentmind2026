from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from agentmind.routing.context import RoutingContext


@dataclass
class StrategyResult:
    agent_id: str
    confidence: float
    reason: str = ""
    alternatives: list[str] = field(default_factory=list)
    reply_text: str = ""


class RoutingStrategy(ABC):

    def __init__(self, name: str, priority: int):
        self.name = name
        self.priority = priority

    @abstractmethod
    async def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        """返回 StrategyResult 或 None（弃权）"""
        ...
