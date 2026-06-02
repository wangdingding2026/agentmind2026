from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Optional


class StreamEventType(str, Enum):
    CONTENT = "content"
    ERROR = "error"


@dataclass
class StreamEvent:
    """流式执行的事件，区分正常内容和错误"""
    type: StreamEventType
    text: str


@dataclass
class AgentCapability:
    """Agent 注册信息，type 决定使用哪个 Executor，config 存放类型特有配置"""

    id: str
    name: str
    type: str  # cli / api / mcp / a2a
    tags: list[str] = field(default_factory=list)
    enabled: bool = True
    timeout: int = 120
    config: dict = field(default_factory=dict)
    # v2.0 新增字段
    description: str = ""
    security_level: str = "local"  # local / cloud / third_party
    estimated_cost: float = 0.0
    avg_latency: float = 0.0
    credibility: float = 0.5  # 来源可信度（已知 Agent 默认 0.8，自动发现默认 0.3）
    auto_discovered: bool = False


@dataclass
class TaskResult:
    success: bool
    output: str
    error: Optional[str] = None
    execution_time_ms: int = 0


class BaseAgentExecutor(ABC):
    """Agent 执行器基类，每种连接协议实现一个子类"""

    def __init__(self, capability: AgentCapability):
        self.capability = capability
        self.is_healthy = True
        self.last_health_check = None

    @abstractmethod
    async def execute(self, instruction: str, context: dict = None) -> TaskResult:
        pass

    @abstractmethod
    async def execute_stream(self, instruction: str, context: dict = None) -> AsyncIterator[StreamEvent]:
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        pass
