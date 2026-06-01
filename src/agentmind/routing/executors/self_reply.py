import json
import logging

from agentmind.routing.context import RoutingDecision
from agentmind.routing.executors.base import ExecutorBase
from agentmind.services.task_service import TaskService
from agentmind.storage.db import record_task_update

logger = logging.getLogger("agentmind")

_SELF_REPLY_SYSTEM = (
    "你是 AgentMind，一个 Agent 管理中枢。你的职责：\n"
    "- 路由用户指令到后端 Agent（代码、搜索、分析等）\n"
    "- 管理各 Agent 生命周期\n"
    "- 维护共享记忆和对话历史\n"
    "- 桥接飞书消息与 Agent 系统\n\n"
    "规则：\n"
    "- 简洁直接，不超过 200 字。\n"
    "- 如实说明自己能做什么、不能做什么。\n"
    "- 如果用户需要执行具体任务（写代码、查天气等），说明你会路由给对应 Agent，不要假装自己能执行。"
)


class SelfReplyExecutor(ExecutorBase):
    """L3 执行器：AgentMind 自答。

    当路由策略决定 agent_id == "agentmind" 且 intent ≠ conversation_history 时使用。
    通过 core LLM 生成回复，不再依赖 StrategyResult.reply_text。
    """

    async def run_json(self, decision: RoutingDecision, trace_id: str, user_id: str):
        reply = await self._build_reply(decision)

        await record_task_update(trace_id, status="executing", routed_agent="agentmind")

        await self._record_success(
            trace_id, "agentmind",
            decision.context.raw_message, reply, user_id,
        )

        logger.info("AgentMind 自答：%s", reply[:60])
        from fastapi.responses import JSONResponse
        return JSONResponse(content={
            "agent_id": "agentmind",
            "result": reply,
            "trace_id": trace_id,
            "status": "completed",
        })

    async def run_stream(self, decision: RoutingDecision, trace_id: str, user_id: str):
        reply = await self._build_reply(decision)

        await record_task_update(trace_id, status="executing", routed_agent="agentmind")

        yield {"event": "status", "data": json.dumps({
            "status": "routed",
            "agent_id": "agentmind",
            "matched_rule": decision.strategy,
            "trace_id": trace_id,
        })}
        yield {"event": "status", "data": json.dumps({
            "status": "executing",
            "agent_id": "agentmind",
            "trace_id": trace_id,
        })}

        await TaskService().record_partial_output(
            trace_id,
            agent_id="agentmind",
            content=reply,
            chunk_index=1,
        )

        yield {"event": "partial", "data": json.dumps({
            "content": reply,
            "trace_id": trace_id,
        })}

        yield {"event": "status", "data": json.dumps({
            "status": "completed",
            "trace_id": trace_id,
            "execution_time_ms": 0,
        })}

        await self._record_success(
            trace_id, "agentmind",
            decision.context.raw_message, reply, user_id,
        )

        logger.info("AgentMind 自答（流式）：%s", reply[:60])

    async def run_text(self, decision: RoutingDecision, trace_id: str, user_id: str):
        reply = await self._build_reply(decision)

        await record_task_update(trace_id, status="executing", routed_agent="agentmind")

        await TaskService().record_partial_output(
            trace_id,
            agent_id="agentmind",
            content=reply,
            chunk_index=1,
        )

        yield reply

        await self._record_success(
            trace_id, "agentmind",
            decision.context.raw_message, reply, user_id,
        )
        logger.info("AgentMind 自答（文本）：%s", reply[:60])

    async def _build_reply(self, decision: RoutingDecision) -> str:
        """生成自答：优先 reply_text（兼容旧策略），否则调用 core LLM。"""
        if decision.reply_text:
            return decision.reply_text

        reply = await self._call_llm_for_reply(decision)
        if reply:
            return reply

        return "抱歉，我暂时无法回答这个问题。请稍后重试。"

    async def _call_llm_for_reply(self, decision: RoutingDecision) -> str | None:
        """调用 core LLM 为 smalltalk / capability 等自答场景生成回复。

        通过 PromptEnvelope 注入 L0 检索到的上下文（与 SingleAgentExecutor 一致）。
        """
        try:
            from agentmind.core.core_llm import core_llm_chat
            from agentmind.routing.envelope import PromptEnvelope

            msg = PromptEnvelope.build(
                decision.context.raw_message,
                decision.context.memory_context,
            )
            messages = [
                {"role": "system", "content": _SELF_REPLY_SYSTEM},
                {"role": "user", "content": msg},
            ]
            return await core_llm_chat(messages, temperature=0.3)
        except Exception:
            logger.debug("SelfReplyExecutor LLM 调用失败", exc_info=True)
            return None
