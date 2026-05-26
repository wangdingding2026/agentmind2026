import asyncio
import inspect
import shlex

import yaml
from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from agentmind.services.config_service import ConfigService
from agentmind.memory.service import MemoryService
from agentmind.services.trace_service import TraceService
from agentmind.storage.db import CONFIG_DIR, get_metrics, get_task_detail, get_task_stats, get_recent_errors, query_tasks

def _mask_config(config: dict) -> dict:
    """脱敏敏感配置字段，只返回 masked 值"""
    return ConfigService(CONFIG_DIR).mask_sensitive(config)


async def _reload_rule_engine(rule_engine):
    result = rule_engine.reload()
    if inspect.isawaitable(result):
        await result


def create_panel_router() -> APIRouter:
    router = APIRouter()

    @router.get("/tasks")
    async def list_tasks(limit: int = 20, offset: int = 0, status: str = None):
        rows = await query_tasks(limit=limit, offset=offset, status=status)
        return {"tasks": rows}

    @router.get("/tasks/stats")
    async def task_stats():
        return await get_task_stats()

    @router.get("/tasks/recent-errors")
    async def recent_errors(limit: int = 5):
        rows = await get_recent_errors(limit=limit)
        return {"errors": rows}

    @router.get("/tasks/{trace_id}")
    async def task_detail(trace_id: str):
        row = await get_task_detail(trace_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return row

    @router.get("/routing/trace/{trace_id}")
    async def routing_trace(trace_id: str):
        trace = await TraceService().get_trace(trace_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        return trace

    @router.get("/agents")
    async def list_agents(request: Request):
        registry = request.app.state.agent_registry
        agents = []
        for agent_id, executor in registry.executors.items():
            cap = executor.capability
            agents.append({
                "id": agent_id,
                "name": cap.name,
                "type": cap.type,
                "tags": cap.tags,
                "enabled": cap.enabled,
                "timeout": cap.timeout,
                "healthy": executor.is_healthy,
                "last_health_check": executor.last_health_check,
                "description": cap.description,
                "security_level": cap.security_level,
                "estimated_cost": cap.estimated_cost,
                "avg_latency": cap.avg_latency,
                "config": _mask_config(cap.config),
            })
        return {"agents": agents}

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
        new_agent = {
            "id": agent_id, "name": name, "type": "cli",
            "tags": tags, "enabled": True, "timeout": 120,
            "config": {"command": command, "health_check": shlex.split(command)[0] + " --version"},
        }

        # 写入 agents.yaml
        path = CONFIG_DIR / "agents.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(data, dict):
            data = {}
        agents = data.get("agents", [])
        if not isinstance(agents, list):
            agents = []
        # 替换已存在的同 ID agent
        agents = [a for a in agents if a.get("id") != agent_id]
        agents.append(new_agent)
        data["agents"] = agents
        path.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False), encoding="utf-8")

        # 立即注册到运行中的 registry
        from agentmind.agents.base import AgentCapability
        from agentmind.agents.cli_executor import CLIExecutor
        cap = AgentCapability(**new_agent)
        request.app.state.agent_registry.executors[agent_id] = CLIExecutor(cap)

        return {"ok": True}

    @router.post("/agents/{agent_id}/restart")
    async def restart_agent(agent_id: str, request: Request):
        registry = request.app.state.agent_registry
        executor = registry.get_executor(agent_id)
        if executor is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        await executor.health_check()
        return {"agent_id": agent_id, "healthy": executor.is_healthy}

    @router.post("/agents/{agent_id}/tags")
    async def update_agent_tags(agent_id: str, request: Request):
        body = await request.json()
        new_tags = body.get("tags", [])
        if not isinstance(new_tags, list):
            return {"ok": False, "error": "tags 必须是数组"}
        registry = request.app.state.agent_registry
        executor = registry.get_executor(agent_id)
        if executor is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        executor.capability.tags = new_tags
        # 持久化
        path = CONFIG_DIR / "agents.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        if isinstance(data, dict):
            for a in data.get("agents", []):
                if isinstance(a, dict) and a.get("id") == agent_id:
                    a["tags"] = new_tags
            path.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False), encoding="utf-8")
        return {"ok": True, "tags": new_tags}

    @router.post("/agents/{agent_id}/toggle")
    async def toggle_agent(agent_id: str, request: Request):
        registry = request.app.state.agent_registry
        executor = registry.get_executor(agent_id)
        if executor is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        # 切换 enabled 状态
        new_enabled = not executor.capability.enabled
        executor.capability.enabled = new_enabled
        # 写入 agents.yaml
        path = CONFIG_DIR / "agents.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        if isinstance(data, dict):
            for a in data.get("agents", []):
                if isinstance(a, dict) and a.get("id") == agent_id:
                    a["enabled"] = new_enabled
            path.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False), encoding="utf-8")
        return {"agent_id": agent_id, "enabled": new_enabled}

    @router.get("/service/status")
    async def service_status(request: Request):
        registry = request.app.state.agent_registry
        stats = await get_task_stats()
        agents = list(registry.executors.values())
        return {
            "agents_total": len(agents),
            "agents_healthy": sum(1 for a in agents if a.is_healthy),
            "tasks_total": stats.get("total", 0),
            "tasks_completed": stats.get("completed", 0),
            "tasks_failed": stats.get("failed", 0),
            "avg_execution_time_ms": stats.get("avg_execution_time_ms", 0),
        }

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
        return await get_metrics()

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
        data = ConfigService(CONFIG_DIR).read_settings()
        fs = data.get("feishu", {}) if isinstance(data, dict) else {}
        return {"app_id": fs.get("app_id", ""), "app_secret": fs.get("app_secret", ""), "enabled": fs.get("enabled", False)}

    @router.post("/feishu/config")
    async def feishu_save_config(request: Request):
        body = await request.json()
        ConfigService(CONFIG_DIR).update_settings_sections({"feishu": {
            "enabled": body.get("enabled", False),
            "app_id": body.get("app_id", ""),
            "app_secret": body.get("app_secret", ""),
        }})
        return {"ok": True}

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
    async def list_rules():
        data = ConfigService(CONFIG_DIR).read_routes()
        return {"rules": data.get("rules", []) if isinstance(data, dict) else []}

    @router.post("/rules")
    async def save_rule(request: Request):
        body = await request.json()
        name = body.get("name", "").strip()
        if not name:
            return {"ok": False, "error": "规则名称不能为空"}
        rule = {
            "name": name,
            "type": body.get("type", "keyword"),
            "patterns": body.get("patterns", []),
            "target_tags": body.get("target_tags", []),
            "priority": body.get("priority", 10),
            "tags": body.get("tags", []),
        }
        service = ConfigService(CONFIG_DIR)
        data = service.read_routes()
        rules = data.get("rules", [])
        if not isinstance(rules, list):
            rules = []
        exist_idx = next((i for i, r in enumerate(rules) if isinstance(r, dict) and r.get("name") == name), None)
        if exist_idx is not None:
            rules[exist_idx] = rule
        else:
            rules.append(rule)
        data["rules"] = rules
        service.write_routes(data)
        # 热加载到运行中的引擎
        await _reload_rule_engine(request.app.state.rule_engine)
        return {"ok": True, "name": name}

    @router.delete("/rules/{name}")
    async def delete_rule(name: str, request: Request):
        service = ConfigService(CONFIG_DIR)
        data = service.read_routes()
        if isinstance(data, dict):
            data["rules"] = [r for r in data.get("rules", []) if isinstance(r, dict) and r.get("name") != name]
            service.write_routes(data)
        await _reload_rule_engine(request.app.state.rule_engine)
        return {"ok": True}

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
        data = ConfigService(CONFIG_DIR).read_settings()
        return {
            "memory": data.get("memory", {}),
            "embedding": data.get("embedding", {}),
            "semantic_router": data.get("semantic_router", {}),
            "history": data.get("history", {}),
            "meta": data.get("core_llm", {}),
        }

    @router.post("/settings")
    async def save_settings(request: Request):
        body = await request.json()
        sections = {}
        if "memory" in body:
            sections["memory"] = body["memory"]
        if "embedding" in body:
            sections["embedding"] = body["embedding"]
        if "semantic_router" in body:
            sections["semantic_router"] = body["semantic_router"]
        if "history" in body:
            sections["history"] = body["history"]
        if "meta" in body:
            sections["core_llm"] = body["meta"]
        ConfigService(CONFIG_DIR).update_settings_sections(sections)
        return {"ok": True}

    @router.get("/feishu/status")
    async def feishu_status(request: Request):
        adapter = getattr(request.app.state, "feishu_adapter", None)
        return {
            "enabled": adapter is not None,
            "connected": adapter is not None and adapter._ws_thread is not None and adapter._ws_thread.is_alive(),
        }

    @router.get("/embedding/status")
    async def embedding_status():
        """返回 embedding 运行时状态（本地模型是否安装、外部 API 是否配置等）"""
        data = ConfigService(CONFIG_DIR).read_settings()
        emb_cfg = data.get("embedding", {})

        has_external = bool(emb_cfg.get("endpoint"))
        try:
            from agentmind.storage.embedding import has_local_embedding
            has_local = has_local_embedding()
        except Exception:
            has_local = False

        # 生成摘要
        parts = []
        if has_external:
            parts.append("外部 API 已配置")
        if has_local:
            parts.append("本地模型已安装")
        if not parts:
            parts.append("未配置")
        summary = " + ".join(parts)

        return {
            "enabled": emb_cfg.get("enabled", False),
            "has_external_api": has_external,
            "has_local_model": has_local,
            "dimension": emb_cfg.get("dimension", 384),
            "summary": summary,
        }

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
