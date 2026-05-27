import asyncio
import inspect

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from agentmind.services.agent_config_service import AgentConfigService
from agentmind.services.agent_control_service import AgentControlService
from agentmind.services.audit_service import AuditService
from agentmind.services.config_service import ConfigService
from agentmind.services.control_plane_overview_service import ControlPlaneOverviewService
from agentmind.services.routing_explanation_service import RoutingExplanationService
from agentmind.services.rule_control_service import RuleControlService
from agentmind.services.settings_control_service import SettingsControlService
from agentmind.services.settings_status_service import SettingsStatusService
from agentmind.services.task_explanation_service import TaskExplanationService
from agentmind.services.task_service import TaskService
from agentmind.memory.service import MemoryService
from agentmind.services.trace_service import TraceService
from agentmind.storage.db import CONFIG_DIR


async def _reload_rule_engine(rule_engine):
    result = rule_engine.reload()
    if inspect.isawaitable(result):
        await result


def _strategy_manager(request: Request):
    strategy_manager = getattr(request.app.state, "strategy_manager", None)
    if strategy_manager is None:
        from agentmind.services.strategy_manager import StrategyManager

        strategy_manager = StrategyManager(
            request.app.state.agent_registry,
            request.app.state.rule_engine,
        )
    return strategy_manager


def _routing_explanation_service(request: Request):
    from agentmind.services.capability_registry import AgentCapabilityRegistry

    return RoutingExplanationService(
        trace_service=TraceService(),
        audit_service=AuditService(),
        capability_registry=AgentCapabilityRegistry(request.app.state.agent_registry),
        strategy_manager=_strategy_manager(request),
    )


def _control_plane_overview_service(request: Request):
    from agentmind.services.capability_registry import AgentCapabilityRegistry

    return ControlPlaneOverviewService(
        task_service=TaskService(),
        capability_registry=AgentCapabilityRegistry(request.app.state.agent_registry),
        strategy_manager=_strategy_manager(request),
        audit_service=AuditService(),
    )


def _agent_control_service(request: Request):
    return AgentControlService(
        request.app.state.agent_registry,
        config_service=ConfigService(CONFIG_DIR),
        agent_config_service=AgentConfigService(CONFIG_DIR),
    )


def _rule_control_service(request: Request):
    return RuleControlService(
        config_service=ConfigService(CONFIG_DIR),
        rule_engine=request.app.state.rule_engine,
    )


def _settings_control_service():
    return SettingsControlService(config_service=ConfigService(CONFIG_DIR))


def _settings_status_service():
    return SettingsStatusService(config_service=ConfigService(CONFIG_DIR))


def create_panel_router() -> APIRouter:
    router = APIRouter()

    @router.get("/tasks")
    async def list_tasks(limit: int = 20, offset: int = 0, status: str = None):
        rows = await TaskService().query_tasks(limit=limit, offset=offset, status=status)
        return {"tasks": rows}

    @router.get("/tasks/stats")
    async def task_stats():
        return await TaskService().get_task_stats()

    @router.get("/tasks/recent-errors")
    async def recent_errors(limit: int = 5):
        rows = await TaskService().get_recent_errors(limit=limit)
        return {"errors": rows}

    @router.get("/tasks/{trace_id}/explanation")
    async def task_explanation(trace_id: str, request: Request):
        service = TaskExplanationService(
            task_service=TaskService(),
            routing_explanation_service=_routing_explanation_service(request),
            audit_service=AuditService(),
        )
        return await service.explain(trace_id)

    @router.get("/tasks/{trace_id}")
    async def task_detail(trace_id: str):
        row = await TaskService().get_task_detail(trace_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return row

    @router.get("/routing/trace/{trace_id}")
    async def routing_trace(trace_id: str):
        trace = await TraceService().get_trace(trace_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        return trace

    @router.get("/audit/events")
    async def audit_events(
        limit: int = 50,
        module: str = "",
        action: str = "",
        agent_id: str = "",
        risk_level: str = "",
        trace_id: str = "",
        actor: str = "",
    ):
        events = await AuditService().query_events(
            limit=limit,
            module=module,
            action=action,
            agent_id=agent_id,
            risk_level=risk_level,
            trace_id=trace_id,
            actor=actor,
        )
        return {"events": events}

    @router.get("/routing/explanations/{trace_id}")
    async def routing_explanation(trace_id: str, request: Request):
        return await _routing_explanation_service(request).explain(trace_id)

    @router.get("/routing/strategies")
    async def routing_strategies(request: Request):
        strategy_manager = _strategy_manager(request)
        return {"strategies": strategy_manager.list_strategies()}

    @router.get("/control/overview")
    async def control_overview(request: Request):
        return await _control_plane_overview_service(request).overview()

    @router.get("/agents")
    async def list_agents(request: Request):
        return {"agents": _agent_control_service(request).list_agents()}

    @router.get("/agents/capabilities")
    async def list_agent_capabilities(request: Request):
        from agentmind.services.capability_registry import AgentCapabilityRegistry

        registry = AgentCapabilityRegistry(request.app.state.agent_registry)
        return {"capabilities": registry.list_profiles()}

    @router.post("/agents/add")
    async def add_agent(request: Request):
        """手动添加 Agent 到 agents.yaml 并立即注册"""
        body = await request.json()
        agent_id = body.get("id", "").strip()
        name = body.get("name", "").strip()
        command = body.get("command", "").strip()
        tags_str = body.get("tags", "").strip()

        if not agent_id or not name or not command:
            return {"ok": False, "error": "ID、名称和命令不能为空"}

        tags = [t.strip() for t in tags_str.split(",") if t.strip()]
        return _agent_control_service(request).add_cli_agent(agent_id, name, command, tags)

    @router.post("/agents/{agent_id}/restart")
    async def restart_agent(agent_id: str, request: Request):
        result = await _agent_control_service(request).restart_agent(agent_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        return result

    @router.post("/agents/{agent_id}/tags")
    async def update_agent_tags(agent_id: str, request: Request):
        body = await request.json()
        new_tags = body.get("tags", [])
        if not isinstance(new_tags, list):
            return {"ok": False, "error": "tags 必须是数组"}
        result = _agent_control_service(request).update_tags(agent_id, new_tags)
        if result is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        return result

    @router.post("/agents/{agent_id}/toggle")
    async def toggle_agent(agent_id: str, request: Request):
        result = _agent_control_service(request).toggle_enabled(agent_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        return result

    @router.get("/service/status")
    async def service_status(request: Request):
        return await _control_plane_overview_service(request).service_status()

    # === v2.0 记忆引擎 API ===

    @router.get("/memory/search")
    async def memory_search(q: str = "", source_agent: str = None, tags: str = None, user_id: str = None, limit: int = 10):
        tag_list = [t.strip() for t in tags.split(",")] if tags else None
        rows = await MemoryService().search_memory(query=q, source_agent=source_agent, tags=tag_list, user_id=user_id, limit=limit)
        return {"memories": rows}

    @router.get("/memory/stats")
    async def memory_stats():
        return await MemoryService().get_memory_stats()

    @router.delete("/memory/{memory_id}")
    async def memory_delete(memory_id: str):
        return {"ok": await MemoryService().delete_memory(memory_id)}

    @router.post("/memory/cleanup")
    async def memory_cleanup(retention_days: int = 30):
        deleted = await MemoryService().cleanup_memory(retention_days=retention_days)
        return {"deleted": deleted}

    # === v2.0 可观测性 ===

    @router.get("/service/metrics")
    async def service_metrics():
        return await TaskService().get_metrics()

    # === v2.0 连接器市场 ===

    @router.get("/connectors")
    async def list_connectors():
        from agentmind.agents.discovery import KNOWN_AGENTS
        return {
            "connectors": [
                {
                    "id": p.id, "name": p.name, "type": p.type,
                    "tags": p.tags, "description": f"自动发现：{', '.join(p.detect_commands)}",
                    "timeout": p.timeout,
                }
                for p in KNOWN_AGENTS
            ]
        }

    # === v3.0 飞书通道 ===

    @router.get("/feishu/config")
    async def feishu_get_config(request: Request):
        return _settings_status_service().get_feishu_config_view()

    @router.post("/feishu/config")
    async def feishu_save_config(request: Request):
        body = await request.json()
        return _settings_control_service().save_feishu_config(body)

    @router.post("/feishu/connect")
    async def feishu_connect(request: Request):
        """保存配置并立即连接飞书通道"""
        body = await request.json()
        app_id = body.get("app_id", "").strip()
        app_secret = body.get("app_secret", "").strip()

        if not app_id or not app_secret:
            return {"ok": False, "error": "App ID 和 App Secret 不能为空"}

        # 1. 持久化到 settings.yaml
        feishu_config = {"enabled": True, "app_id": app_id, "app_secret": app_secret}
        ConfigService(CONFIG_DIR).update_settings_sections({"feishu": feishu_config})

        # 2. 停掉旧连接（如果有）
        old = getattr(request.app.state, "feishu_adapter", None)
        if old:
            await old.stop()

        # 3. 更新 app.state.settings 以便重启时记住
        request.app.state.settings["feishu"] = feishu_config

        # 4. 启动新连接
        try:
            from agentmind.channels.feishu import FeishuAdapter
            from agentmind.api.router import route_stream

            async def feishu_callback(msg: str, sender_id: str):
                async for chunk in route_stream(
                    msg, sender_id,
                    request.app.state.agent_registry,
                    request.app.state.rule_engine,
                    request.app.state.settings,
                ):
                    yield chunk

            adapter = FeishuAdapter(
                app_id=app_id,
                app_secret=app_secret,
                route_callback=feishu_callback,
            )
            await adapter.start()
            await asyncio.sleep(0.5)
            if adapter._ws_thread and adapter._ws_thread.is_alive():
                request.app.state.feishu_adapter = adapter
                return {"ok": True, "connected": True}
            else:
                await adapter.stop()
                return {"ok": False, "error": "WebSocket 连接失败，请检查 app_id/app_secret 是否正确，或查看服务日志"}
        except Exception as e:
            return {"ok": False, "error": f"连接失败: {e}"}

    @router.post("/feishu/disconnect")
    async def feishu_disconnect(request: Request):
        """断开飞书通道"""
        adapter = getattr(request.app.state, "feishu_adapter", None)
        if adapter:
            await adapter.stop()
            request.app.state.feishu_adapter = None
        service = ConfigService(CONFIG_DIR)
        data = service.read_settings()
        if isinstance(data, dict) and "feishu" in data:
            data["feishu"]["enabled"] = False
            service.write_settings(data)
        return {"ok": True}

    # === 路由规则管理 ===

    @router.get("/rules")
    async def list_rules(request: Request):
        return {"rules": _rule_control_service(request).list_rules()}

    @router.post("/rules")
    async def save_rule(request: Request):
        body = await request.json()
        name = body.get("name", "").strip()
        if not name:
            return {"ok": False, "error": "规则名称不能为空"}
        return await _rule_control_service(request).save_rule(body)

    @router.delete("/rules/{name}")
    async def delete_rule(name: str, request: Request):
        return await _rule_control_service(request).delete_rule(name)

    # === 活跃会话 ===

    @router.get("/sessions")
    async def active_sessions():
        from agentmind.routing.side_effects.session_registry import session_registry
        discussions = []
        for uid, disc in session_registry.list_discussions().items():
            discussions.append({"user_id": uid, "stop": disc.get("stop", False)})
        # 最近执行中的任务（用同步版本）
        import asyncio as _aio
        tasks = await _aio.to_thread(
            __import__("agentmind.storage.db", fromlist=["_query_tasks_sync"])._query_tasks_sync,
            limit=5, status="executing",
        )
        return {"discussions": discussions, "executing_tasks": tasks}

    # === 通用设置（memory + embedding）===

    @router.get("/settings")
    async def get_settings():
        return _settings_status_service().get_settings_view()

    @router.post("/settings")
    async def save_settings(request: Request):
        body = await request.json()
        return _settings_control_service().save_settings(body)

    @router.get("/feishu/status")
    async def feishu_status(request: Request):
        adapter = getattr(request.app.state, "feishu_adapter", None)
        return {
            "enabled": adapter is not None,
            "connected": adapter is not None and adapter._ws_thread is not None and adapter._ws_thread.is_alive(),
        }

    @router.get("/embedding/status")
    async def embedding_status():
        return _settings_status_service().get_embedding_status()

    # === v3.0 Attach 接管 ===

    @router.post("/tasks/{trace_id}/attach")
    async def attach_to_task(trace_id: str, request: Request):
        session_id = request.query_params.get("session_id", "")
        if not session_id:
            return {"error": "缺少 session_id 参数"}
        attach_registry = getattr(request.app.state, "attach_registry", None)
        if not attach_registry:
            return {"error": "Attach 功能未启用"}
        attach_registry.bind(session_id, trace_id)
        return {"status": "attached", "trace_id": trace_id}

    # === v2.0 Peek 实时流 ===

    @router.get("/tasks/{trace_id}/stream")
    async def panel_task_stream(trace_id: str):
        from agentmind.routing.side_effects.session_registry import session_registry as _sr
        register_stream_listener = _sr.register_stream_listener
        unregister_stream_listener = _sr.unregister_stream_listener

        queue = register_stream_listener(trace_id)

        async def event_gen():
            try:
                while True:
                    chunk = await queue.get()
                    if chunk is None:
                        break
                    yield chunk
            finally:
                unregister_stream_listener(trace_id, queue)

        return EventSourceResponse(event_gen())

    return router
