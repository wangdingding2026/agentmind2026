import asyncio
import logging

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from agentmind.api.models import RouteRequest
from agentmind.memory.service import MemoryService
from agentmind.routing.protocol_router import ProtocolRouter
from agentmind.services import routing_service as routing_service_module
from agentmind.services.routing_service import RoutingService

logger = logging.getLogger("agentmind")
router = APIRouter()

from agentmind.routing.side_effects.session_registry import session_registry as _session


def register_stream_listener(trace_id: str) -> asyncio.Queue:
    return _session.register_stream_listener(trace_id)


def unregister_stream_listener(trace_id: str, queue: asyncio.Queue):
    _session.unregister_stream_listener(trace_id, queue)


def cleanup_stale_streams(ttl_seconds: int = 600):
    return _session.cleanup_stale_streams(ttl_seconds)


def _step_security_intercept(msg: str, agent_registry) -> str | None:
    """安全拦截（router.py 本地副本）。

    TODO: router.py 的 handle_attached_command 与 routing_service 的 _handle_attached_command
    几乎相同（仅 SSE data 序列化方式不同：str() vs json.dumps()），应统一到 routing_service。
    统一后删除此函数。
    """
    route = ProtocolRouter(agent_registry=agent_registry).match(msg)
    if route and route.kind == "security_intercept":
        logger.info("安全层拦截：检测到敏感信息，降级到本地 Agent %s", route.value)
        return route.value
    return None


async def handle_attached_command(trace_id: str, route_req, request: Request):
    from pathlib import Path
    from agentmind.storage.db import get_task_detail, record_attached_turn

    agent_registry = request.app.state.agent_registry
    security_agent_id = _step_security_intercept(route_req.message, agent_registry)
    original = await get_task_detail(trace_id)
    if not original:
        from fastapi.responses import JSONResponse
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
        from fastapi.responses import JSONResponse
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
                        yield {"event": "partial", "data": str({"content": event.text, "trace_id": trace_id})}
                        full_output.append(event.text)
                    elif event.type.value == "error":
                        yield {"event": "error", "data": str({"error": event.text, "trace_id": trace_id})}
            except Exception as e:
                yield {"event": "error", "data": str({"error": str(e), "trace_id": trace_id})}
            result = "".join(full_output)
            await record_attached_turn(trace_id, route_req.message, result)
            yield {"event": "status", "data": str({"status": "complete", "trace_id": trace_id})}
        return EventSourceResponse(attach_event_gen())

    result = await executor.execute(context_prompt)
    await record_attached_turn(trace_id, route_req.message, result.output if result.success else result.error or "")
    if result.success:
        from fastapi.responses import JSONResponse
        return JSONResponse(content={"trace_id": trace_id, "agent_id": agent_id, "result": result.output})
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=500, content={"trace_id": trace_id, "error": result.error})


@router.post("/route")
async def route_request(route_req: RouteRequest, request: Request):
    return await RoutingService(request.app).route_request(route_req.model_dump(), request)





async def route_stream(msg: str, user_id: str, agent_registry, engine, settings, send_func=None, strategy_manager=None):
    async for chunk in routing_service_module.route_stream(
        msg,
        user_id,
        agent_registry,
        engine,
        settings,
        send_func=send_func,
        strategy_manager=strategy_manager,
    ):
        yield chunk
