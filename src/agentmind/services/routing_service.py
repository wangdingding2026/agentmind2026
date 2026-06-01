from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from agentmind.api.models import RouteRequest
from agentmind.core.trace import generate_trace_id
from agentmind.governance import CPE, CPERequest
from agentmind.memory.service import MemoryService
from agentmind.orchestration.engine import OrchestrationEngine
from agentmind.orchestration.models import OrchestrationPlan
from agentmind.routing.context import RequestIdentity, RoutingDecision
from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor
from agentmind.routing.executors.self_reply import SelfReplyExecutor
from agentmind.routing.executors.single_agent import SingleAgentExecutor
from agentmind.routing.pipeline import RoutingPipeline
from agentmind.routing.protocol_router import ProtocolRouter
from agentmind.routing.semantic_intent import SemanticIntentType
from agentmind.routing.side_effects.session_registry import session_registry as _session
from agentmind.routing.side_effects.trace_recorder import TraceRecorder
from agentmind.services.audit_service import AuditService
from agentmind.services.orchestration_service import OrchestrationService
from agentmind.storage.db import record_attached_turn, record_task_end, record_task_start, record_task_update

logger = logging.getLogger("agentmind")


class RoutingService:
    def __init__(self, app):
        self.app = app

    async def route_request(self, payload: dict[str, Any], request: Request | None = None):
        route_req = RouteRequest(**payload)
        request = request or self.app
        return await _route_request_impl(route_req, request)


def _get_app(request_or_app):
    return getattr(request_or_app, "app", request_or_app)


def _build_cpe_request_for_routing(
    *,
    trace_id: str,
    user_id: str,
    agent_id: str,
    message: str,
    agent_registry,
    memories: list[dict] | None = None,
) -> CPERequest:
    executor = agent_registry.get_executor(agent_id) if hasattr(agent_registry, "get_executor") else None
    if executor is None:
        executor = getattr(agent_registry, "executors", {}).get(agent_id)
    security_level = ""
    if executor is not None:
        security_level = getattr(getattr(executor, "capability", None), "security_level", "")
    return CPERequest(
        trace_id=trace_id,
        user_id=user_id,
        agent_id=agent_id,
        agent_security_level=security_level,
        context={"message": message, "surface": "routing"},
        memory_items=memories or [],
    )


async def _record_cpe_routing_dry_run(cpe_request: CPERequest) -> None:
    try:
        decision = CPE().evaluate(cpe_request)
        await AuditService().record_cpe_decision(
            request=cpe_request,
            decision=decision,
            actor="system",
            payload={"surface": "routing", "mode": "dry_run"},
        )
    except Exception:
        logger.debug("记录 CPE routing dry-run audit 失败", exc_info=True)


def _select_executor(decision: RoutingDecision, agent_registry):
    intent = decision.semantic_intent.intent if decision.semantic_intent else None
    if decision.agent_id == "agentmind":
        if intent == SemanticIntentType.CONVERSATION_HISTORY:
            return ConversationHistoryExecutor(agent_registry)
        return SelfReplyExecutor(agent_registry)
    return SingleAgentExecutor(agent_registry)


def register_stream_listener(trace_id: str) -> asyncio.Queue:
    return _session.register_stream_listener(trace_id)


def unregister_stream_listener(trace_id: str, queue: asyncio.Queue):
    _session.unregister_stream_listener(trace_id, queue)


def cleanup_stale_streams(ttl_seconds: int = 600):
    return _session.cleanup_stale_streams(ttl_seconds)


async def _broadcast_stream_chunks(trace_id: str, chunks):
    async for chunk in chunks:
        _session.broadcast_stream_chunk(trace_id, chunk)
        yield chunk


def _step_security_intercept(msg: str, agent_registry) -> str | None:
    """安全拦截：检测敏感信息，降级到本地 Agent。

    委托 ProtocolRouter 做确定性的信息检测，不再各自维护正则。
    """
    route = ProtocolRouter(agent_registry=agent_registry).match(msg)
    if route and route.kind == "security_intercept":
        logger.info("安全层拦截：检测到敏感信息，降级到本地 Agent %s", route.value)
        return route.value
    return None


@dataclass
class _PipelineResult:
    trace_id: str
    decision: RoutingDecision


async def _resolve_routing_decision(
    msg: str,
    user_id: str,
    session_id: str,
    agent_registry,
    engine,
    settings: dict,
    strategy_manager=None,
    is_retry: bool = False,
) -> _PipelineResult:
    """共享的管道执行入口：生成 trace_id、构建 identity、运行路由管道。

    调用方负责 task_record 和 executor 分发，因为 HTTP/通道路径的记录时机和输出格式不同。
    """
    trace_id = generate_trace_id()
    identity = RequestIdentity(
        trace_id=trace_id,
        user_id=user_id,
        session_id=session_id,
    )
    pipeline = RoutingPipeline(agent_registry, engine, strategy_manager=strategy_manager)
    decision = await pipeline.run(msg, identity, settings, is_retry)
    return _PipelineResult(trace_id=trace_id, decision=decision)


async def _handle_attached_command(trace_id: str, route_req: RouteRequest, request: Request):
    from agentmind.storage.db import get_task_detail

    app = _get_app(request)
    agent_registry = app.state.agent_registry
    security_agent_id = _step_security_intercept(route_req.message, agent_registry)
    original = await get_task_detail(trace_id)
    if not original:
        return JSONResponse(status_code=404, content={"error": "原任务不存在"})

    full_context = original.get("error_message") or ""
    result_path = original.get("full_result_path")
    if result_path:
        rp = Path(result_path)
        if rp.is_file():
            full_context = rp.read_text(encoding="utf-8") or full_context
    if not full_context:
        full_context = original.get("result_summary") or "无结果"

    agent_id = security_agent_id or original.get("routed_agent") or next((aid for aid, ex in agent_registry.executors.items() if ex.is_healthy), None)
    executor = agent_registry.get_executor(agent_id) if agent_id else None
    if not executor:
        return JSONResponse(status_code=503, content={"error": f"Agent {agent_id} 不可用"})

    context_prompt = (
        f"[系统注入：你正在继续一个未完成的任务]\n"
        f"上一次的任务指令：{original.get('user_message', '')}\n"
        f"上一次的执行结果：\n{full_context[:8000]}\n\n"
        f"请基于以上上下文，继续处理用户的最新指令：\n"
        f"{route_req.message}"
    )

    if route_req.stream:
        async def attach_event_gen():
            full_output = []
            try:
                async for event in executor.execute_stream(context_prompt):
                    if event.type.value == "content":
                        yield {"event": "partial", "data": json.dumps({"content": event.text, "trace_id": trace_id})}
                        full_output.append(event.text)
                    elif event.type.value == "error":
                        yield {"event": "error", "data": json.dumps({"error": event.text, "trace_id": trace_id})}
            except Exception as e:
                yield {"event": "error", "data": json.dumps({"error": str(e), "trace_id": trace_id})}
            result = "".join(full_output)
            await record_attached_turn(trace_id, route_req.message, result)
            yield {"event": "status", "data": json.dumps({"status": "complete", "trace_id": trace_id})}
        return EventSourceResponse(_broadcast_stream_chunks(trace_id, attach_event_gen()))

    result = await executor.execute(context_prompt)
    await record_attached_turn(trace_id, route_req.message, result.output if result.success else result.error or "")
    if result.success:
        return JSONResponse(content={"trace_id": trace_id, "agent_id": agent_id, "result": result.output})
    return JSONResponse(status_code=500, content={"trace_id": trace_id, "error": result.error})


async def _route_request_impl(route_req: RouteRequest, request: Request):
    if _is_new_session_cmd(route_req.message):
        try:
            sid = await MemoryService().new_session(route_req.user_id or "")
            return JSONResponse(content={
                "agent_id": "agentmind",
                "result": f"已开启新会话 ({sid})，Working Memory 已清空",
                "trace_id": generate_trace_id(),
                "status": "completed",
            })
        except Exception as e:
            logger.warning("/new 会话创建失败: %s", e)
            return JSONResponse(status_code=500, content={
                "error": f"会话创建失败: {e}",
                "trace_id": generate_trace_id(),
            })

    plan = _match_orchestration(route_req.message)
    if plan:
        app = _get_app(request)
        agent_registry = app.state.agent_registry
        plan_id = plan.get("plan_id", "")
        chunks = _execute_orchestration_plan(plan, route_req.user_id or "", agent_registry, None, route_req.message)
        if plan_id:
            chunks = _broadcast_stream_chunks(plan_id, chunks)
        return EventSourceResponse(chunks)

    if route_req.session_id:
        app = _get_app(request)
        attach_registry = getattr(app.state, "attach_registry", None)
        if attach_registry:
            bound_tid = attach_registry.get_bound_task(route_req.session_id)
            if bound_tid:
                return await _handle_attached_command(bound_tid, route_req, request)

    msg = route_req.message
    app = _get_app(request)
    agent_registry = app.state.agent_registry
    engine = app.state.rule_engine
    settings = getattr(app.state, "settings", None) or {}

    pipeline_result = await _resolve_routing_decision(
        msg=msg,
        user_id=route_req.user_id or "",
        session_id=route_req.session_id or "",
        agent_registry=agent_registry,
        engine=engine,
        settings=settings,
        strategy_manager=getattr(app.state, "strategy_manager", None),
        is_retry=route_req.is_retry,
    )
    trace_id = pipeline_result.trace_id
    decision = pipeline_result.decision

    await record_task_start(trace_id, msg)
    await record_task_update(trace_id, status="routing")

    if decision is not None:
        await record_task_update(trace_id, status="routing", matched_rule=decision.strategy or "pipeline", routed_agent=decision.agent_id)
        await TraceRecorder.record_decision(trace_id, decision, route_req.user_id or "")
        await _record_cpe_routing_dry_run(
            _build_cpe_request_for_routing(
                trace_id=trace_id,
                user_id=route_req.user_id or "",
                agent_id=decision.agent_id,
                message=msg,
                agent_registry=agent_registry,
                memories=decision.context.memories if decision.context else [],
            )
        )

        if not decision.agent_id:
            await record_task_end(trace_id, "failed", error_message="无可用Agent")
            if route_req.stream:
                async def _no_agent_sse():
                    yield {"event": "error", "data": json.dumps({
                        "error": "没有可用的 Agent，请检查 Agent 是否已安装并启用",
                        "trace_id": trace_id,
                    })}
                return EventSourceResponse(_broadcast_stream_chunks(trace_id, _no_agent_sse()))
            return JSONResponse(status_code=503, content={
                "error": "没有可用的 Agent，请检查 Agent 是否已安装并启用",
                "trace_id": trace_id,
            })

        executor = _select_executor(decision, agent_registry)

        if route_req.stream:
            chunks = executor.run_stream(decision, trace_id, route_req.user_id or "")
            return EventSourceResponse(_broadcast_stream_chunks(trace_id, chunks))
        return await executor.run_json(decision, trace_id, route_req.user_id or "")

    return JSONResponse(status_code=500, content={"error": "routing failed", "trace_id": trace_id})


async def route_stream(msg: str, user_id: str, agent_registry, engine, settings, send_func=None, strategy_manager=None):
    logger.info("route_stream 收到消息: user=%s msg=%s", user_id[:12] if user_id else "-", msg[:60])
    if _is_new_session_cmd(msg) and user_id:
        try:
            sid = await MemoryService().new_session(user_id)
            yield f"【AgentMind】\n已开启新会话 ({sid})\nWorking Memory 已清空，旧 conversation 已关闭"
            return
        except Exception as e:
            logger.warning("/new 会话创建失败: %s", e)
            yield f"【AgentMind】\n会话创建失败：{e}"
            return

    plan = _match_orchestration(msg)
    if plan:
        async for _event in _execute_orchestration_plan(plan, user_id, agent_registry, send_func, msg):
            pass
        yield "【AgentMind】\n编排执行完成"
        return

    parsed = _parse_discussion(msg, agent_registry)
    if parsed and send_func:
        mentions, topic = parsed
        healthy = [m for m in mentions if agent_registry.get_executor(m) and agent_registry.get_executor(m).is_healthy]
        if len(healthy) >= 2:
            _session.start_discussion(user_id)
            asyncio.create_task(_run_discussion(topic, healthy[:4], user_id, agent_registry, send_func))
            yield "【AgentMind】\n讨论已启动..."
            return

    pipeline_result = await _resolve_routing_decision(
        msg=msg,
        user_id=user_id,
        session_id="",
        agent_registry=agent_registry,
        engine=engine,
        settings=settings,
        strategy_manager=strategy_manager,
    )
    trace_id = pipeline_result.trace_id
    decision = pipeline_result.decision

    await record_task_start(trace_id, msg)
    await record_task_update(trace_id, status="routing", matched_rule=decision.strategy or "pipeline", routed_agent=decision.agent_id)

    if not decision.agent_id:
        yield "【AgentMind】\n没有可用的 Agent，请检查 Agent 是否已安装并启用"
        return

    if decision.agent_id == "agentmind":
        yield "【AgentMind】\n"
        executor = _select_executor(decision, agent_registry)
        async for chunk in executor.run_text(decision, trace_id, user_id):
            yield chunk
    else:
        executor = SingleAgentExecutor(agent_registry)
        agent_label = f"【{decision.agent_id}】\n"
        yield agent_label
        async for chunk in executor.run_text(decision, trace_id, user_id):
            yield chunk


def _match_orchestration(msg: str) -> dict | None:
    return OrchestrationService().match_plan(msg)


async def _execute_orchestration_plan(plan: dict, user_id: str, agent_registry, send_func, user_msg: str = ""):
    dag_plan = OrchestrationPlan(plan_id=plan.get("plan_id", ""), steps=plan.get("steps", []))
    try:
        async for event in OrchestrationEngine().execute_events(
            dag_plan,
            agent_registry,
            initial_instruction=user_msg,
        ):
            if send_func:
                if event["event"] == "partial":
                    await send_func(event["data"].get("content", ""))
                elif event["event"] == "node_status" and event["data"].get("status") == "failed":
                    await send_func(f"编排步骤 {event['data'].get('step_id')} 失败：{event['data'].get('error')}")
            yield {"event": event["event"], "data": json.dumps(event.get("data", {}))}
    except ValueError as e:
        if send_func:
            await send_func(f"编排执行失败：{e}")
        yield {"event": "error", "data": json.dumps({"error": f"编排执行失败：{e}"})}


def _resolve_agent_mention(raw: str, agent_registry) -> str | None:
    from agentmind.routing.strategies.explicit_directive import ExplicitDirective
    return ExplicitDirective(agent_registry)._resolve(raw)


def _parse_discussion(msg: str, agent_registry) -> tuple[list[str], str] | None:
    import re as _re
    raw_mentions = _re.findall(r'@(\S+)', msg)
    if len(raw_mentions) < 2:
        return None
    if not _re.search(r'讨论|辩论|聊聊|说说', msg):
        return None
    resolved = []
    for raw in raw_mentions:
        aid = _resolve_agent_mention(raw, agent_registry)
        if aid and aid not in resolved:
            resolved.append(aid)
    if len(resolved) < 2:
        return None
    topic = _re.sub(r'@\S+\s*', '', msg)
    topic = _re.sub(r'^(讨论|辩论|聊聊|说说)[：:]\s*', '', topic).strip()
    return resolved, topic or "未指定主题"


async def _run_discussion(topic: str, agent_ids: list[str], user_id: str, agent_registry, send_msg):
    import asyncio as _asyncio_impl

    agents = []
    for aid in agent_ids[:4]:
        ex = agent_registry.get_executor(aid)
        if ex and ex.is_healthy:
            agents.append(ex)
    if len(agents) < 2:
        await send_msg("需要至少 2 个健康的 Agent 才能讨论")
        return

    history: list[tuple[str, str]] = []
    turn = 0
    names = "、".join(a.capability.name for a in agents)
    await send_msg(f"讨论开始：{topic}\n参与：{names}\n各 Agent 将轮流发言，发送「停」结束讨论")

    while True:
        disc = _session.is_discussion_active(user_id)
        if not disc:
            break
        agent = agents[turn % len(agents)]
        turn += 1
        _word_limit = ""
        _lm = re.search(r'(\d+)\s*字', topic)
        if _lm:
            _word_limit = f"限{_lm.group(1)}字"
        if not _word_limit:
            _word_limit = "限300字"
        if not history:
            context = f'关于 "{topic}"，请发表你的核心观点。{_word_limit}。'
        else:
            prev_name, prev_response = history[-1]
            context = f'{prev_name} 认为：\n"""{prev_response[:800]}"""\n\n你是否同意？如果同意，补充新的论据；如果不同意，直接反驳并说明理由。{_word_limit}。'
        full_output = []
        error_message = ""
        response_path = agent.capability.config.get("response_path", "")
        try:
            async for event in agent.execute_stream(context):
                if event.type.value == "content":
                    full_output.append(event.text)
                elif event.type.value == "error":
                    error_message = event.text
                if not _session.is_discussion_active(user_id):
                    break
        except Exception as e:
            await send_msg(f"【{agent.capability.name}】发言失败：{e}")
            continue
        response = "".join(full_output)
        if response_path:
            from agentmind.routing.utils import extract_response_path
            response = extract_response_path(response, response_path)
        if not response.strip():
            response = f"（无输出：{error_message[:150]}）" if error_message else "（本轮无内容）"
        history.append((agent.capability.name, response))
        truncated = response[:1500]
        if len(response) > 1500:
            truncated += "\n...(发言过长已截断)"
        await send_msg(f"【{agent.capability.name}】\n{truncated}")
        turn_trace_id = generate_trace_id()
        await record_task_start(turn_trace_id, f"讨论：{topic}（第{turn}轮）")
        await record_task_end(turn_trace_id, "completed", agent.capability.id, result=response, execution_time_ms=0)
        try:
            await MemoryService().write_memory({
                "memory_id": f"discuss-{user_id}-t{turn}",
                "content": f"讨论：{topic}（第{turn}轮）",
                "summary": f"[{agent.capability.name}] {response[:500]}",
                "source_agent": agent.capability.id,
                "source_task_id": turn_trace_id,
                "tags": ["discussion", f"user:{user_id}"],
                "user_id": user_id,
            })
        except Exception:
            pass
        if not _session.is_discussion_active(user_id):
            break
        await _asyncio_impl.sleep(3)

    if history and agents:
        summarizer = agents[0]
        summary_context = f'以下是关于 "{topic}" 的完整讨论：\n'
        for name, resp in history:
            summary_context += f"\n{name}：{resp[:800]}"
        summary_context += (
            f"\n\n请输出结构化结论，按以下格式。{_word_limit}：\n"
            "1. 核心结论（一句话概括讨论结果）\n"
            "2. 共识点（列出双方都同意的）\n"
            "3. 分歧点（列出双方立场不同的）\n"
            "4. 行动建议（基于讨论结果，下一步该做什么）"
        )
        full_output = []
        try:
            async for event in summarizer.execute_stream(summary_context):
                if event.type.value == "content":
                    full_output.append(event.text)
        except Exception:
            pass
        summary_text = "".join(full_output)
        if not summary_text.strip():
            summary_text = "（总结生成失败）"
        summary_rp = summarizer.capability.config.get("response_path", "")
        if summary_rp:
            from agentmind.routing.utils import extract_response_path
            summary_text = extract_response_path(summary_text, summary_rp)
        if summary_text.strip():
            await send_msg(f"总结（by {summarizer.capability.name}）\n{summary_text[:2000]}")
            sum_trace_id = generate_trace_id()
            await record_task_start(sum_trace_id, f"讨论总结：{topic}")
            await record_task_end(sum_trace_id, "completed", summarizer.capability.id, result=summary_text, execution_time_ms=0)

    await send_msg(f"讨论结束，共 {turn} 轮发言")
    _session.end_discussion(user_id)


def _is_new_session_cmd(msg: str) -> bool:
    text = msg.strip()
    import re as _re
    text = _re.sub(r'@\S+\s*', '', text).strip()
    if text.startswith("/new"):
        if len(text) == 4:
            return True
        ch = text[4]
        if ch.isspace() or ord(ch) > 127:
            return True
    return False
