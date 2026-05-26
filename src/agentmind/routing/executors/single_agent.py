import json
import logging
import time

from fastapi.responses import JSONResponse

from agentmind.agents.base import StreamEventType, TaskResult
from agentmind.api.models import RouteResponse
from agentmind.routing.context import RoutingDecision
from agentmind.routing.executors.base import ExecutorBase
from agentmind.storage.db import record_task_end, record_task_update

logger = logging.getLogger("agentmind")


class SingleAgentExecutor(ExecutorBase):
    """L3 执行器：单 Agent 任务。

    负责 PromptEnvelope 构建、Agent 执行、fallback_chain 重试、
    任务记录和记忆写入。
    """

    # ── 非流式（含 fallback_chain 重试）──

    async def run_json(
        self, decision: RoutingDecision, trace_id: str, user_id: str,
    ) -> RouteResponse | JSONResponse:
        envelope = self._build_envelope(decision.context)
        await record_task_update(trace_id, status="executing")

        chain = [decision.agent_id] + decision.fallback_chain
        start = time.time()
        agent_id, result, error = await self._execute_with_fallback(chain, envelope)
        exec_time = int((time.time() - start) * 1000)

        if agent_id and result:
            await self._record_success(
                trace_id, agent_id,
                decision.context.raw_message, result.output, user_id,
                execution_time_ms=result.execution_time_ms or exec_time,
            )
            return RouteResponse(
                trace_id=trace_id,
                agent_id=agent_id,
                matched_rule=decision.strategy,
                confidence=decision.confidence,
                result=result.output,
                execution_time_ms=result.execution_time_ms or exec_time,
            )

        await self._record_failure(trace_id, decision.agent_id, error)
        return JSONResponse(status_code=500, content={
            "error": error or "所有 Agent 执行失败",
            "trace_id": trace_id,
            "agent_id": decision.agent_id,
        })

    # ── 流式（含 fallback_chain 重试）──

    async def run_stream(self, decision: RoutingDecision, trace_id: str, user_id: str):
        envelope = self._build_envelope(decision.context)
        chain = [decision.agent_id] + decision.fallback_chain

        yield {"event": "status", "data": json.dumps({
            "status": "routed",
            "agent_id": decision.agent_id,
            "matched_rule": decision.strategy,
            "trace_id": trace_id,
        })}
        yield {"event": "status", "data": json.dumps({
            "status": "executing",
            "agent_id": decision.agent_id,
            "trace_id": trace_id,
        })}
        await record_task_update(trace_id, status="executing")

        start = time.time()
        full_output = []
        has_error = False
        error_message = None
        executed_agent_id = decision.agent_id
        any_chunk_sent = False
        buffered_errors: list[dict] = []  # 缓存错误事件，仅在全部失败后发出

        for agent_id in chain:
            ex = self._find_executor(agent_id)
            if not ex:
                continue

            executed_agent_id = agent_id
            full_output = []
            has_error = False
            error_message = None

            async for event in ex.execute_stream(envelope):
                if event.type == StreamEventType.CONTENT:
                    chunk = {"event": "partial", "data": json.dumps({
                        "content": event.text,
                        "trace_id": trace_id,
                    })}
                    yield chunk
                    full_output.append(event.text)
                    any_chunk_sent = True
                elif event.type == StreamEventType.ERROR:
                    # 缓存错误，先不发给客户端（等所有 fallback 失败后再发）
                    buffered_errors.append({"event": "error", "data": json.dumps({
                        "error": event.text,
                        "trace_id": trace_id,
                    })})
                    has_error = True
                    error_message = event.text

            if not has_error:
                buffered_errors.clear()
                break
            if any_chunk_sent:
                buffered_errors.clear()
                break

        # 所有 Agent 都失败时才发送缓存的错误
        if has_error and not any_chunk_sent:
            for err in buffered_errors[-1:]:  # 只发最后一个错误
                yield err

        execution_time = int((time.time() - start) * 1000)

        if has_error and not any_chunk_sent:
            await record_task_end(
                trace_id, "failed", executed_agent_id,
                execution_time_ms=execution_time, error_message=error_message,
            )
        elif has_error and any_chunk_sent:
            # 部分输出 + 错误：仍记录为 completed
            result_text = "".join(full_output)
            await record_task_end(
                trace_id, "completed", executed_agent_id,
                execution_time_ms=execution_time, result=result_text,
            )
        else:
            result_text = "".join(full_output)
            yield {"event": "status", "data": json.dumps({
                "status": "completed",
                "trace_id": trace_id,
                "execution_time_ms": execution_time,
            })}
            await self._record_success(
                trace_id, executed_agent_id,
                decision.context.raw_message, result_text, user_id,
                execution_time_ms=execution_time,
            )

    # ── 文本流式（飞书通道，yield 纯文本）──

    async def run_text(self, decision: RoutingDecision, trace_id: str, user_id: str):
        envelope = self._build_envelope(decision.context)
        chain = [decision.agent_id] + decision.fallback_chain

        # 检查是否需要 response_path JSON 提取（如 OpenClaw 的 payloads.0.text）
        first_ex = self._find_executor(decision.agent_id)
        response_path = (
            first_ex.capability.config.get("response_path", "")
            if first_ex else ""
        )

        await record_task_update(trace_id, status="executing")

        start = time.time()
        full_output = []
        has_error = False
        error_message = None
        executed_agent_id = decision.agent_id
        any_chunk_sent = False
        buffered_errors: list[str] = []

        for agent_id in chain:
            ex = self._find_executor(agent_id)
            if not ex:
                continue

            executed_agent_id = agent_id
            full_output = []
            has_error = False
            error_message = None

            async for event in ex.execute_stream(envelope):
                if event.type == StreamEventType.CONTENT:
                    if not response_path:
                        yield event.text
                    full_output.append(event.text)
                    any_chunk_sent = True
                elif event.type == StreamEventType.ERROR:
                    buffered_errors.append(event.text)
                    has_error = True
                    error_message = event.text

            if not has_error:
                buffered_errors.clear()
                break
            if any_chunk_sent:
                buffered_errors.clear()
                break

        execution_time = int((time.time() - start) * 1000)

        if has_error and not any_chunk_sent:
            for err_text in buffered_errors[-1:]:
                yield err_text or "执行出错"
            await record_task_end(
                trace_id, "failed", executed_agent_id,
                execution_time_ms=execution_time, error_message=error_message,
            )
        else:
            result_text = "".join(full_output)

            # response_path JSON 提取（如 OpenClaw 返回 {"payloads":[{"text":"..."}]}）
            if response_path:
                from agentmind.routing.utils import extract_response_path
                result_text = extract_response_path(result_text, response_path)
                yield result_text

            await self._record_success(
                trace_id, executed_agent_id,
                decision.context.raw_message, result_text, user_id,
                execution_time_ms=execution_time,
            )
