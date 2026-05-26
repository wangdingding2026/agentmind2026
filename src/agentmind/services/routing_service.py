from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from agentmind.api.models import RouteRequest
from agentmind.core.trace import generate_trace_id
from agentmind.memory.service import MemoryService
from agentmind.routing.context import RequestIdentity
from agentmind.routing.executors.self_reply import SelfReplyExecutor
from agentmind.routing.executors.single_agent import SingleAgentExecutor
from agentmind.routing.pipeline import RoutingPipeline
from agentmind.routing.side_effects.session_registry import session_registry as _session
from agentmind.routing.side_effects.trace_recorder import TraceRecorder
from agentmind.storage.db import record_attached_turn, record_task_end, record_task_start, record_task_update

logger = logging.getLogger("agentmind")
_SENSITIVE_RE = re.compile(
    r'(sk-[a-zA-Z0-9]{20,}|api_key\s*=\s*[\"\'][^\"\']+|password\s*=\s*[\"\'][^\"\']+)',
    re.IGNORECASE,
)


class RoutingService:
    def __init__(self, app):
        self.app = app

    async def route_request(self, payload: dict[str, Any], request: Request | None = None):
        route_req = RouteRequest(**payload)
        request = request or self.app
        return await _route_request_impl(route_req, request)


def _get_app(request_or_app):
    return getattr(request_or_app, "app", request_or_app)


def register_stream_listener(trace_id: str) -> asyncio.Queue:
    return _session.register_stream_listener(trace_id)


def unregister_stream_listener(trace_id: str, queue: asyncio.Queue):
    _session.unregister_stream_listener(trace_id, queue)


def cleanup_stale_streams(ttl_seconds: int = 600):
    return _session.cleanup_stale_streams(ttl_seconds)


def _step_security_intercept(msg: str, agent_registry) -> str | None:
    if not _SENSITIVE_RE.search(msg):
        return None
    local_agents = agent_registry.get_healthy_agents_by_security_level("local")
    if local_agents:
        logger.info("安全层拦截：检测到敏感信息，降级到本地 Agent %s", local_agents[0])
        return local_agents[0]
    logger.warning("检测到敏感信息但无可用本地 Agent，继续正常路由")
    return None


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
        return EventSourceResponse(attach_event_gen())

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
        return EventSourceResponse(_execute_orchestration_plan(plan, route_req.user_id or "", agent_registry, None, route_req.message))

    if route_req.session_id:
        app = _get_app(request)
        attach_registry = getattr(app.state, "attach_registry", None)
        if attach_registry:
            bound_tid = attach_registry.get_bound_task(route_req.session_id)
            if bound_tid:
                return await _handle_attached_command(bound_tid, route_req, request)

    trace_id = generate_trace_id()
    msg = route_req.message
    app = _get_app(request)
    agent_registry = app.state.agent_registry
    engine = app.state.rule_engine
    settings = getattr(app.state, "settings", None) or {}

    _step_security_intercept(msg, agent_registry)
    await record_task_start(trace_id, msg)
    await record_task_update(trace_id, status="routing")

    identity = RequestIdentity(
        trace_id=trace_id,
        user_id=route_req.user_id or "",
        session_id=route_req.session_id or "",
    )
    pipeline = RoutingPipeline(agent_registry, engine)
    decision = await pipeline.run(msg, identity, settings, route_req.is_retry)

    if decision is not None:
        await record_task_update(trace_id, status="routing", matched_rule=decision.strategy or "pipeline", routed_agent=decision.agent_id)
        await TraceRecorder.record_decision(trace_id, decision, route_req.user_id or "")

        if not decision.agent_id:
            await record_task_end(trace_id, "failed", error_message="无可用Agent")
            if route_req.stream:
                async def _no_agent_sse():
                    yield {"event": "error", "data": json.dumps({
                        "error": "没有可用的 Agent，请检查 Agent 是否已安装并启用",
                        "trace_id": trace_id,
                    })}
                return EventSourceResponse(_no_agent_sse())
            return JSONResponse(status_code=503, content={
                "error": "没有可用的 Agent，请检查 Agent 是否已安装并启用",
                "trace_id": trace_id,
            })

        if decision.agent_id == "agentmind":
            executor = SelfReplyExecutor(agent_registry)
        else:
            executor = SingleAgentExecutor(agent_registry)

        if route_req.stream:
            return EventSourceResponse(executor.run_stream(decision, trace_id, route_req.user_id or ""))
        return await executor.run_json(decision, trace_id, route_req.user_id or "")

    return JSONResponse(status_code=500, content={"error": "routing failed", "trace_id": trace_id})


async def route_stream(msg: str, user_id: str, agent_registry, engine, settings, send_func=None):
    trace_id = generate_trace_id()
    start_time = asyncio.get_event_loop().time()
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
        await _execute_orchestration_plan(plan, user_id, agent_registry, send_func, msg)
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

    use_new = settings.get("routing", {}).get("use_new_pipeline", False) if isinstance(settings, dict) else False
    identity = RequestIdentity(trace_id=trace_id, user_id=user_id, session_id="")
    pipeline = RoutingPipeline(agent_registry, engine)
    decision = await pipeline.run(msg, identity, settings)

    await record_task_start(trace_id, msg)
    await record_task_update(trace_id, status="routing", matched_rule=decision.strategy or "pipeline", routed_agent=decision.agent_id)

    if not decision.agent_id:
        yield "【AgentMind】\n没有可用的 Agent，请检查 Agent 是否已安装并启用"
        return

    if decision.agent_id == "agentmind":
        yield "【AgentMind】\n"
        executor = SelfReplyExecutor(agent_registry)
        async for chunk in executor.run_text(decision, trace_id, user_id):
            yield chunk
    else:
        executor = SingleAgentExecutor(agent_registry)
        agent_label = f"【{decision.agent_id}】\n"
        yield agent_label
        async for chunk in executor.run_text(decision, trace_id, user_id):
            yield chunk


def _match_orchestration(msg: str) -> dict | None:
    from agentmind.api.orchestration import _load_orchestrations, _increment_orchestration_usage
    plans = _load_orchestrations()
    msg_lower = msg.lower()
    for plan in plans:
        for tw in plan.get("trigger_words", []):
            if tw.lower() in msg_lower:
                _increment_orchestration_usage(plan["plan_id"])
                return plan
    return None


async def _execute_orchestration_plan(plan: dict, user_id: str, agent_registry, send_func, user_msg: str = ""):
    from agentmind.api.orchestration import validate_dag, topological_sort
    from agentmind.api.models import OrchestrationStep

    steps = [OrchestrationStep(**s) for s in plan.get("steps", [])]
    try:
        validate_dag(steps)
        sorted_steps = topological_sort(steps)
    except ValueError as e:
        if send_func:
            await send_func(f"编排执行失败：{e}")
        return

    step_results: dict[int, str] = {}
    for step in sorted_steps:
        executor = agent_registry.get_executor(step.agent_id)
        if not executor or not executor.is_healthy:
            continue
        instruction = user_msg if user_msg else step.instruction
        if step.depends_on:
            context_parts = []
            for dep_id in step.depends_on:
                if dep_id in step_results:
                    context_parts.append(step_results[dep_id][:1000])
            if context_parts:
                instruction = "前置步骤结果：\n" + "\n".join(context_parts) + "\n\n当前任务：" + instruction
        try:
            task_result = await executor.execute(instruction)
            result = task_result.output if task_result.success else (task_result.error or "执行失败")
        except Exception as e:
            result = str(e)
        step_results[step.step_id] = result[:4000]
        if send_func:
            await send_func(f"【{executor.capability.name}】{result[:1500]}")


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
