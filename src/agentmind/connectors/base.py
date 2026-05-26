from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from agentmind.agents.base import AgentCapability, StreamEvent, TaskResult


class AgentConnector(ABC):
    def __init__(self, executor):
        self._executor = executor

    @abstractmethod
    async def invoke(self, instruction: str, context: dict | None = None) -> TaskResult:
        ...

    @abstractmethod
    async def stream(
        self,
        instruction: str,
        context: dict | None = None,
    ) -> AsyncIterator[StreamEvent]:
        ...

    @abstractmethod
    async def health(self) -> bool:
        ...

    @abstractmethod
    def capabilities(self) -> AgentCapability:
        ...


class ExecutorConnector(AgentConnector):
    async def invoke(self, instruction: str, context: dict | None = None) -> TaskResult:
        return await self._executor.execute(instruction, context)

    async def stream(
        self,
        instruction: str,
        context: dict | None = None,
    ) -> AsyncIterator[StreamEvent]:
        async for event in self._executor.execute_stream(instruction, context):
            yield event

    async def health(self) -> bool:
        return await self._executor.health_check()

    def capabilities(self) -> AgentCapability:
        return self._executor.capability
