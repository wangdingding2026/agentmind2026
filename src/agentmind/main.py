import asyncio
import logging
import os
import secrets
import socket
import time

import yaml
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from agentmind.agents.discovery import discover_and_generate
from agentmind.agents.registry import AgentRegistry
from agentmind.config.defaults import generate_default_configs
from agentmind.core.rule_engine import RuleEngine
from agentmind.memory.workers.scheduler import MemoryWorkerScheduler
from agentmind.storage.db import DATA_HOME, initialize_data_directory, mark_timed_out_tasks_retriable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("agentmind")


def find_available_port(start_port: int = 8765, max_tries: int = 10) -> int:
    """从 start_port 开始，找第一个可用端口"""
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


async def periodic_health_check(registry: AgentRegistry):
    """每 60 秒执行一次健康检查"""
    while True:
        await asyncio.sleep(60)
        await registry.run_health_checks()


async def periodic_memory_cleanup():
    """每 3600 秒（1小时）清理一次过期记忆"""
    from agentmind.storage.memory import cleanup_memory
    while True:
        await asyncio.sleep(3600)
        try:
            await cleanup_memory(retention_days=30)
        except Exception:
            pass


async def periodic_stream_cleanup():
    """每 300 秒（5分钟）清理无监听器的流注册表条目"""
    from agentmind.routing.side_effects.session_registry import session_registry as _sr
    cleanup_stale_streams = _sr.cleanup_stale_streams
    while True:
        await asyncio.sleep(300)
        try:
            n = cleanup_stale_streams(ttl_seconds=600)
            if n:
                logger.debug("流注册表清理：移除 %d 个过期条目", n)
        except Exception:
            pass


async def periodic_workspace_cleanup():
    """每 3600 秒清理超过 7 天的旧工作区"""
    import shutil
    from agentmind.storage.db import DATA_HOME

    while True:
        await asyncio.sleep(3600)
        try:
            ws_dir = DATA_HOME / "workspaces"
            if not ws_dir.is_dir():
                continue
            cutoff = time.time() - 86400 * 7
            for child in ws_dir.iterdir():
                if child.is_dir() and child.stat().st_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True)
        except Exception:
            pass


def _load_or_generate_token() -> tuple[str, bool]:
    """加载已有 token 或生成新的本地认证 token。返回 (token, is_new)"""
    token_path = DATA_HOME / "config" / "auth.token"
    if token_path.exists():
        token = token_path.read_text(encoding="utf-8").strip()
        # 校验非空且足够长（至少 32 字符 hex token）
        if len(token) < 32:
            logger.warning("auth.token 内容无效（长度 %d），将重新生成", len(token))
            os.remove(token_path)
        else:
            # 确保权限收紧
            if token_path.stat().st_mode & 0o077:
                os.chmod(token_path, 0o600)
            return token, False
    token = secrets.token_hex(32)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    # 创建文件前设置 umask 等效：写后收紧权限
    token_path.write_text(token, encoding="utf-8")
    os.chmod(token_path, 0o600)
    return token, True


def _is_local_origin(origin: str) -> bool:
    """精确校验 Origin 是否为本地来源"""
    if not origin:
        return False
    try:
        parsed = urlparse(origin)
        return (parsed.scheme == "http"
                and parsed.hostname in ("127.0.0.1", "localhost", "::1"))
    except Exception:
        return False


def create_app(port: int) -> FastAPI:
    agents_path = DATA_HOME / "config" / "agents.yaml"
    agent_registry = AgentRegistry(agents_path)
    rule_engine = RuleEngine(DATA_HOME / "config" / "routes.yaml", agent_registry=agent_registry)
    auth_token, token_is_new = _load_or_generate_token()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await agent_registry.run_health_checks()
        mark_timed_out_tasks_retriable()  # v2.0 崩溃恢复
        health_task = asyncio.create_task(periodic_health_check(agent_registry))

        # embedding 状态检测
        emb_cfg = settings.get("embedding", {}) if isinstance(settings, dict) else {}
        if emb_cfg.get("enabled"):
            has_external = bool(emb_cfg.get("endpoint"))
            try:
                from agentmind.storage.embedding import has_local_embedding
                has_local = has_local_embedding()
            except Exception:
                has_local = False

            if has_external and has_local:
                logger.info("向量搜索: 外部 API + 本地模型（后备）")
            elif has_external:
                logger.info("向量搜索: 外部 API（无本地后备，pip install agentmind[embedding] 可启用）")
            elif has_local:
                logger.info("向量搜索: 本地模型（all-MiniLM-L6-v2, 384维）")
            else:
                logger.warning("向量搜索: 未配置 embedding 来源，语义召回不可用")
                logger.warning("  方案1: pip install agentmind[embedding]（本地模型，~2GB）")
                logger.warning("  方案2: 在面板配置外部 embedding API")

        # v3.0 飞书通道
        feishu_adapter = None
        feishu_cfg = settings.get("feishu", {}) if isinstance(settings, dict) else {}
        if feishu_cfg.get("enabled") and feishu_cfg.get("app_id") and feishu_cfg.get("app_secret"):
            try:
                from agentmind.channels.feishu import FeishuAdapter
                from agentmind.api.router import route_stream

                feishu_adapter = None

                async def feishu_callback(msg: str, sender_id: str):
                    async def _send(text: str):
                        if feishu_adapter:
                            await feishu_adapter.send_message(sender_id, text)
                    async for chunk in route_stream(
                        msg, sender_id,
                        app.state.agent_registry,
                        app.state.rule_engine,
                        app.state.settings,
                        send_func=_send,
                    ):
                        yield chunk

                feishu_adapter = FeishuAdapter(
                    app_id=feishu_cfg["app_id"],
                    app_secret=feishu_cfg["app_secret"],
                    route_callback=feishu_callback,
                )
                await feishu_adapter.start()
                app.state.feishu_adapter = feishu_adapter
                logger.info("飞书通道已启动")
            except Exception as e:
                logger.warning("飞书通道启动失败: %s", e)
        # v4 Memory Workers
        scheduler = MemoryWorkerScheduler()
        app.state.memory_scheduler = scheduler
        worker_task = asyncio.create_task(scheduler.start(settings))

        memory_task = asyncio.create_task(periodic_memory_cleanup())
        workspace_task = asyncio.create_task(periodic_workspace_cleanup())
        stream_task = asyncio.create_task(periodic_stream_cleanup())
        logger.info("AgentMind 服务已启动，API: http://127.0.0.1:%d/v1/", port)
        logger.info("面板地址: http://127.0.0.1:%d/panel/", port)
        if token_is_new:
            token_path = DATA_HOME / "config" / "auth.token"
            logger.info("已生成认证 Token，路径: %s (权限 0o600)", token_path)
            logger.info("API 调用时使用 Authorization: Bearer <token>，或通过面板自动认证")
        yield
        if feishu_adapter:
            await feishu_adapter.stop()
        worker_task.cancel()
        await scheduler.stop()
        health_task.cancel()
        memory_task.cancel()
        workspace_task.cancel()
        stream_task.cancel()
        try:
            await health_task
        except asyncio.CancelledError:
            pass
        try:
            await memory_task
        except asyncio.CancelledError:
            pass
        try:
            await workspace_task
        except asyncio.CancelledError:
            pass
        try:
            await stream_task
        except asyncio.CancelledError:
            pass

    app = FastAPI(title="AgentMind", version="1.0.0", lifespan=lifespan)
    app.state.agent_registry = agent_registry
    app.state.auth_token = auth_token

    # 加载 settings.yaml
    settings_path = DATA_HOME / "config" / "settings.yaml"
    settings = {}
    if settings_path.exists():
        try:
            with open(settings_path) as f:
                settings = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("settings.yaml 加载失败: %s，使用默认配置", e)
    app.state.settings = settings

    # 接口鉴权
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        needs_auth = (
            request.method in ("POST", "PUT", "DELETE", "PATCH")
            or request.url.path.startswith("/panel/api/")
        )
        if needs_auth:
            # 1. Origin 校验：拒绝非本地的跨站请求（CSRF 防护）
            origin = request.headers.get("origin", "")
            if origin and not _is_local_origin(origin):
                return JSONResponse(status_code=403, content={"error": "Forbidden origin"})

            # 2. 提取 token：优先 Authorization header，其次 cookie
            req_token = ""
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                req_token = auth_header[7:]
            if not req_token:
                req_token = request.cookies.get("agentmind_token", "")

            if req_token != auth_token:
                return JSONResponse(status_code=401, content={"error": "Unauthorized: missing or invalid token"})
        return await call_next(request)

    @app.get("/")
    async def root():
        return RedirectResponse(url="/panel/")

    # 面板首页：设置认证 cookie，面板请求自动携带
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
            max_age=86400 * 7,  # 7 天，过期后重新访问面板刷新
            secure=False,  # 本地 HTTP 服务
        )
        return response

    from agentmind.api.attach_registry import AttachRegistry
    app.state.attach_registry = AttachRegistry()
    app.state.rule_engine = rule_engine
    from agentmind.routing.pipeline import RoutingPipeline
    app.state.routing_pipeline = RoutingPipeline(agent_registry, rule_engine)
    app.state.agents_config_path = agents_path

    # 注册 API 路由
    from agentmind.api.agents import router as agents_router
    from agentmind.api.router import router as route_router
    from agentmind.api.orchestration import router as orch_router
    app.include_router(agents_router, prefix="/v1")
    app.include_router(route_router, prefix="/v1")
    app.include_router(orch_router, prefix="/v1")

    # 控制面板：API 路由必须在 StaticFiles mount 之前注册
    from agentmind.panel import create_panel_router
    from fastapi.staticfiles import StaticFiles

    panel_router = create_panel_router()
    app.include_router(panel_router, prefix="/panel/api")

    static_dir = Path(__file__).parent / "panel" / "static"
    if static_dir.is_dir():
        app.mount("/panel", StaticFiles(directory=str(static_dir), html=False), name="panel")
    else:
        logger.warning("面板静态资源目录不存在: %s，面板页面将不可用", static_dir)

    # v1.0 优雅关闭：依赖 Uvicorn 原生连接排空机制
    # v2.0 将结合 job_state.db 实现任务级中断恢复

    return app


async def async_main():
    """异步主入口：初始化 + 自动发现 + 启动服务"""
    initialize_data_directory()
    generate_default_configs()

    agents_path = DATA_HOME / "config" / "agents.yaml"
    logger.info("正在扫描已安装的 Agent...")
    await discover_and_generate(agents_path)

    port = find_available_port(8765)
    app = create_app(port)

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, loop="asyncio",
        log_level="warning",  # 屏蔽面板轮询的 INFO 访问日志
    )
    server = uvicorn.Server(config)
    await server.serve()


def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(async_main())
    loop.close()


if __name__ == "__main__":
    main()
