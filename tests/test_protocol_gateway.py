import pytest

from agentmind.agents.base import AgentCapability, StreamEvent, StreamEventType, TaskResult


class _FakeExecutor:
    def __init__(self, capability, *, healthy=True):
        self.capability = capability
        self.is_healthy = healthy
        self.last_health_check = None
        self.invocations = []

    async def execute(self, instruction: str, context: dict = None):
        self.invocations.append(("execute", instruction, context))
        return TaskResult(
            success=True,
            output=f"{self.capability.type}:{instruction}",
            execution_time_ms=7,
        )

    async def execute_stream(self, instruction: str, context: dict = None):
        self.invocations.append(("stream", instruction, context))
        yield StreamEvent(StreamEventType.CONTENT, f"{self.capability.type}:{instruction}")

    async def health_check(self):
        self.last_health_check = "checked"
        return self.is_healthy


class _Registry:
    def __init__(self, executors):
        self.executors = executors

    def get_executor(self, agent_id):
        return self.executors.get(agent_id)


def _executor(agent_id: str, protocol: str, *, healthy=True):
    cap = AgentCapability(
        id=agent_id,
        name=f"{protocol} agent",
        type=protocol,
        tags=["test"],
        enabled=True,
        timeout=5,
        config={},
    )
    return _FakeExecutor(cap, healthy=healthy)


@pytest.mark.parametrize("protocol", ["cli", "api", "mcp", "a2a"])
@pytest.mark.asyncio
async def test_protocol_gateway_invokes_all_supported_protocols(protocol):
    from agentmind.services.protocol_gateway import ProtocolGateway

    executor = _executor("agent1", protocol)
    gateway = ProtocolGateway(_Registry({"agent1": executor}))

    result = await gateway.invoke("agent1", "hello", context={"trace_id": "t1"})

    assert result.success is True
    assert result.output == f"{protocol}:hello"
    assert executor.invocations == [("execute", "hello", {"trace_id": "t1"})]


@pytest.mark.asyncio
async def test_protocol_gateway_streams_agent_events():
    from agentmind.services.protocol_gateway import ProtocolGateway

    executor = _executor("agent1", "cli")
    gateway = ProtocolGateway(_Registry({"agent1": executor}))

    events = [event async for event in gateway.stream("agent1", "hello")]

    assert [event.text for event in events] == ["cli:hello"]


@pytest.mark.asyncio
async def test_protocol_gateway_returns_failed_result_for_unavailable_agent():
    from agentmind.services.protocol_gateway import ProtocolGateway

    gateway = ProtocolGateway(_Registry({}))

    result = await gateway.invoke("missing", "hello")

    assert result.success is False
    assert "不可用" in result.error
