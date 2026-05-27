from __future__ import annotations

import asyncio
import logging
import os
import secrets
import shutil
import socket
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from agentmind.agents.discovery import discover_and_generate
from agentmind.agents.registry import AgentRegistry
from agentmind.channels.hub import ChannelHub
from agentmind.config.defaults import generate_default_configs
from agentmind.core.rule_engine import RuleEngine
from agentmind.memory.workers.scheduler import MemoryWorkerScheduler
from agentmind.services.config_service import ConfigService
from agentmind.services.session_runtime_service import SessionRuntimeService
from agentmind.storage.db import DATA_HOME, initialize_data_directory, mark_timed_out_tasks_retriable

logger = logging.getLogger("agentmind")


def find_available_port(start_port: int = 8765, max_tries: int = 10) -> int:
    """从 start_port 开始，找第一个可用端口。"""
    for port in range(start_port, start_port + max_tries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError(
        f"无法找到可用端口（尝试了 {start_port}-{start_port + max_tries - 1}）"
    )


def load_or_generate_token(data_home: Path) -> tuple[str, bool]:
    """加载已有 token 或生成新的本地认证 token。返回 (token, is_new)。"""
    token_path = data_home / "config" / "auth.token"
    if token_path.exists():
        token = token_path.read_text(encoding="utf-8").strip()
        if len(token) < 32:
            logger.warning("auth.token 内容无效（长度 %d），将重新生成", len(token))
            os.remove(token_path)
        else:
            if token_path.stat().st_mode & 0o077:
                os.chmod(token_path, 0o600)
            return token, False
    token = secrets.token_hex(32)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(token, encoding="utf-8")
    os.chmod(token_path, 0o600)
    return token, True


def is_local_origin(origin: str) -> bool:
    """精确校验 Origin 是否为本地来源。"""
    if not origin:
        return False
    try:
        parsed = urlparse(origin)
        return (
            parsed.scheme == "http"
            and parsed.hostname in ("127.0.0.1", "localhost", "::1")
        )
    except Exception:
        return False


async def _periodic_health_check(registry: AgentRegistry):
    while True:
        await asyncio.sleep(60)
        await registry.run_health_checks()


async def _periodic_memory_cleanup():
    from agentmind.memory.service import MemoryService

    while True:
        await asyncio.sleep(3600)
        try:
            await MemoryService().cleanup_memory(retention_days=30)
        except Exception:
            pass


async def _periodic_stream_cleanup():
    from agentmind.routing.side_effects.session_registry import session_registry as _sr

    cleanup_stale_streams = _sr.cleanup_stale_streams
    while True:
        await asyncio.sleep(300)
        try:
            cleanup_stale_streams(ttl_seconds=600)
        except Exception:
            pass


async def _periodic_workspace_cleanup(data_home: Path):
    while True:
        await asyncio.sleep(3600)
        try:
            ws_dir = data_home / "workspaces"
            if not ws_dir.is_dir():
                continue
            cutoff = time.time() - 86400 * 7
            for child in ws_dir.iterdir():
                if child.is_dir() and child.stat().st_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True)
        except Exception:
            pass


async def _maybe_start_feishu(
    app: FastAPI,
    settings: dict[str, Any],
    config_service: ConfigService,
):
    return await ChannelHub(config_service=config_service).maybe_start_feishu(app, settings)


@dataclass(slots=True)
class AgentMindBootstrapper:
    port: int
    data_home: Path = DATA_HOME

    def create_app(self) -> FastAPI:
        config_service = ConfigService(self.data_home / "config")
        try:
            settings = config_service.read_settings()
        except Exception as e:
            logger.warning("settings.yaml 加载失败: %s，使用默认配置", e)
            settings = {}

        agents_path = self.data_home / "config" / "agents.yaml"
        rule_path = self.data_home / "config" / "routes.yaml"
        agent_registry = AgentRegistry(agents_path)
        rule_engine = RuleEngine(rule_path, agent_registry=agent_registry)
        strategy_manager = __import__(
            "agentmind.services.strategy_manager", fromlist=["StrategyManager"]
        ).StrategyManager(agent_registry, rule_engine)
        auth_token, token_is_new = load_or_generate_token(self.data_home)

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            await agent_registry.run_health_checks()
            mark_timed_out_tasks_retriable()
            SessionRuntimeService().restore_runtime_state()
            health_task = asyncio.create_task(_periodic_health_check(agent_registry))
            memory_task = asyncio.create_task(_periodic_memory_cleanup())
            workspace_task = asyncio.create_task(_periodic_workspace_cleanup(self.data_home))
            stream_task = asyncio.create_task(_periodic_stream_cleanup())

            scheduler = MemoryWorkerScheduler()
            app.state.memory_scheduler = scheduler
            worker_task = asyncio.create_task(scheduler.start(settings))
            feishu_adapter = await _maybe_start_feishu(
                app,
                settings,
                config_service=config_service,
            )
            if feishu_adapter is not None:
                app.state.feishu_adapter = feishu_adapter

            logger.info("AgentMind 服务已启动，API: http://127.0.0.1:%d/v1/", self.port)
            logger.info("面板地址: http://127.0.0.1:%d/panel/", self.port)
            if token_is_new:
                token_path = self.data_home / "config" / "auth.token"
                logger.info("已生成认证 Token，路径: %s (权限 0o600)", token_path)
                logger.info("API 调用时使用 Authorization: Bearer <token>，或通过面板自动认证")

            try:
                yield
            finally:
                if feishu_adapter:
                    await feishu_adapter.stop()
                worker_task.cancel()
                await scheduler.stop()
                for task in (health_task, memory_task, workspace_task, stream_task):
                    task.cancel()
                for task in (health_task, memory_task, workspace_task, stream_task):
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        app = FastAPI(title="AgentMind", version="1.0.0", lifespan=lifespan)
        app.state.agent_registry = agent_registry
        app.state.auth_token = auth_token
        app.state.settings = settings
        app.state.rule_engine = rule_engine
        app.state.strategy_manager = strategy_manager
        app.state.attach_registry = __import__(
            "agentmind.api.attach_registry", fromlist=["AttachRegistry"]
        ).AttachRegistry()
        app.state.routing_pipeline = __import__(
            "agentmind.routing.pipeline", fromlist=["RoutingPipeline"]
        ).RoutingPipeline(agent_registry, rule_engine, strategy_manager=strategy_manager)
        app.state.agents_config_path = agents_path

        @app.middleware("http")
        async def auth_middleware(request: Request, call_next):
            needs_auth = (
                request.method in ("POST", "PUT", "DELETE", "PATCH")
                or request.url.path.startswith("/panel/api/")
            )
            if needs_auth:
                origin = request.headers.get("origin", "")
                if origin and not is_local_origin(origin):
                    return JSONResponse(
                        status_code=403,
                        content={"error": "Forbidden origin"},
                    )

                req_token = ""
                auth_header = request.headers.get("authorization", "")
                if auth_header.startswith("Bearer "):
                    req_token = auth_header[7:]
                if not req_token:
                    req_token = request.cookies.get("agentmind_token", "")
                if req_token != auth_token:
                    return JSONResponse(
                        status_code=401,
                        content={"error": "Unauthorized: missing or invalid token"},
                    )
            return await call_next(request)

        @app.get("/")
        async def root():
            return RedirectResponse(url="/panel/")

        @app.get("/panel/")
        async def panel_index():
            static_dir = Path(__file__).parent / "panel" / "static"
            index_path = static_dir / "index.html"
            if not index_path.is_file():
                return HTMLResponse(
                    content="<html><body><h2>面板不可用</h2><p>静态资源未找到，请从源码运行或重新安装。</p></body></html>",
                    status_code=503,
                )
            response = HTMLResponse(content=index_path.read_text(encoding="utf-8"))
            response.set_cookie(
                key="agentmind_token",
                value=auth_token,
                httponly=True,
                samesite="strict",
                path="/",
                max_age=86400 * 7,
                secure=False,
            )
            return response

        self._register_app_routes(app)
        return app

    def _register_app_routes(self, app: FastAPI) -> None:
        from fastapi.staticfiles import StaticFiles

        from agentmind.api.agents import router as agents_router
        from agentmind.api.orchestration import router as orch_router
        from agentmind.api.router import router as route_router
        from agentmind.panel import create_panel_router

        app.include_router(agents_router, prefix="/v1")
        app.include_router(route_router, prefix="/v1")
        app.include_router(orch_router, prefix="/v1")
        app.include_router(create_panel_router(), prefix="/panel/api")

        static_dir = Path(__file__).parent / "panel" / "static"
        if static_dir.is_dir():
            app.mount("/panel", StaticFiles(directory=str(static_dir), html=False), name="panel")
        else:
            logger.warning("面板静态资源目录不存在: %s，面板页面将不可用", static_dir)


async def async_main():
    """异步主入口：初始化 + 自动发现 + 启动服务。"""
    initialize_data_directory()
    generate_default_configs()

    agents_path = DATA_HOME / "config" / "agents.yaml"
    logger.info("正在扫描已安装的 Agent...")
    await discover_and_generate(agents_path)

    port = find_available_port(8765)
    app = AgentMindBootstrapper(port=port, data_home=DATA_HOME).create_app()

    import uvicorn

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        loop="asyncio",
        log_level="warning",
    )
    server = uvicorn.Server(config)
    await server.serve()
