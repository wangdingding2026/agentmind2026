import logging
from abc import ABC

from agentmind.agents.base import TaskResult
from agentmind.routing.context import RoutingContext
from agentmind.routing.envelope import PromptEnvelope
from agentmind.routing.side_effects.memory_writer import MemoryWriter
from agentmind.services.protocol_gateway import ProtocolGateway
from agentmind.storage.db import record_task_end

logger = logging.getLogger("agentmind")


class ExecutorBase(ABC):
    """L3 执行器基类。

    提供公共方法：envelope 构建、Agent 查找、fallback_chain 重试循环、
    任务记录。子类实现 run_json / run_stream。
    """

    def __init__(self, agent_registry):
        self._registry = agent_registry
        self._gateway = ProtocolGateway(agent_registry)

    def _build_envelope(self, ctx: RoutingContext) -> str:
        return PromptEnvelope.build(ctx.raw_message, ctx.memory_context or ctx.memories)

    def _find_executor(self, agent_id: str):
        if not agent_id:
            return None
        ex = self._registry.get_executor(agent_id)
        return ex if ex and ex.is_healthy else None

    async def _execute_with_fallback(self, chain: list[str], envelope: str):
        """遍历 chain 执行，成功返回 (agent_id, TaskResult, None)，
        全部失败返回 (None, None, last_error)。
        """
        last_error = None
        for agent_id in chain:
            ex = self._find_executor(agent_id)
            if not ex:
                continue
            try:
                gateway = getattr(self, "_gateway", None)
                if gateway is None:
                    gateway = ProtocolGateway(self._registry)
                    self._gateway = gateway
                result: TaskResult = await gateway.invoke(agent_id, envelope)
                if result.success:
                    return agent_id, result, None
                last_error = result.error
            except Exception as e:
                last_error = str(e)
                logger.debug("Agent %s 执行失败: %s", agent_id, e)
        return None, None, last_error

    async def _record_success(
        self, trace_id: str, agent_id: str,
        raw_message: str, output: str, user_id: str,
        execution_time_ms: int = 0,
    ):
        await record_task_end(
            trace_id, "completed", agent_id,
            result=output, execution_time_ms=execution_time_ms,
        )
        # agentmind 自答不写入任务记忆，避免记忆查询产生自循环
        if agent_id != "agentmind":
            await MemoryWriter.write_task(trace_id, agent_id, raw_message, output, user_id)

    async def _record_failure(
        self, trace_id: str, agent_id: str,
        error: str, execution_time_ms: int = 0,
    ):
        await record_task_end(
            trace_id, "failed", agent_id,
            error_message=error or "所有 Agent 执行失败",
            execution_time_ms=execution_time_ms,
        )
