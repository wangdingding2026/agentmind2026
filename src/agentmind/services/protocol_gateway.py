from __future__ import annotations

from typing import AsyncIterator

from agentmind.agents.base import AgentCapability, StreamEvent, StreamEventType, TaskResult
from agentmind.connectors import A2AConnector, CLIConnector, HTTPConnector, MCPConnector
from agentmind.connectors.base import AgentConnector


class ProtocolGateway:
    def __init__(self, agent_registry):
        self._registry = agent_registry

    async def invoke(
        self,
        agent_id: str,
        instruction: str,
        context: dict | None = None,
    ) -> TaskResult:
        connector = self._connector_for(agent_id)
        if connector is None:
            return TaskResult(success=False, output="", error=f"Agent {agent_id} 不可用")
        return await connector.invoke(instruction, context)

    async def stream(
        self,
        agent_id: str,
        instruction: str,
        context: dict | None = None,
    ) -> AsyncIterator[StreamEvent]:
        connector = self._connector_for(agent_id)
        if connector is None:
            yield StreamEvent(StreamEventType.ERROR, f"Agent {agent_id} 不可用")
            return
        async for event in connector.stream(instruction, context):
            yield event

    async def health(self, agent_id: str) -> bool:
        connector = self._connector_for(agent_id, require_healthy=False)
        if connector is None:
            return False
        return await connector.health()

    def capabilities(self, agent_id: str) -> AgentCapability | None:
        connector = self._connector_for(agent_id, require_healthy=False)
        if connector is None:
            return None
        return connector.capabilities()

    def _connector_for(
        self,
        agent_id: str,
        *,
        require_healthy: bool = True,
    ) -> AgentConnector | None:
        if not agent_id:
            return None
        executor = self._registry.get_executor(agent_id)
        if executor is None:
            return None
        if require_healthy and not executor.is_healthy:
            return None
        connector_cls = _CONNECTOR_MAP.get(executor.capability.type, CLIConnector)
        return connector_cls(executor)


_CONNECTOR_MAP = {
    "cli": CLIConnector,
    "api": HTTPConnector,
    "mcp": MCPConnector,
    "a2a": A2AConnector,
}
