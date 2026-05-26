# AgentMind Phase 1 Main Startup Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Slim `src/agentmind/main.py` into a thin entrypoint by extracting app bootstrap, startup/shutdown wiring, and background-task management into a dedicated startup module without changing routing behavior.

**Architecture:** Keep `create_app()` as the public compatibility hook, but move the real setup into a startup-focused module that owns token loading, app-state initialization, lifespan orchestration, Feishu startup, and periodic maintenance tasks. Leave `api/router.py` and Phase 1 RoutingService work out of scope. The new code should preserve all existing app behavior so current integration tests keep passing while `main.py` becomes a delegating wrapper.

**Tech Stack:** Python 3.12, FastAPI, asyncio, uvicorn, PyYAML, pytest, pytest-asyncio.

---

## Current Baseline

- Phase 1 service-layer package is complete and green.
- Reported test baseline before this package:

```bash
pytest -q
```

Expected baseline:

```text
342 passed, 4 warnings
```

## Files

Create:

- `src/agentmind/startup.py`
- `tests/test_startup.py`

Modify:

- `src/agentmind/main.py`
- `tests/test_auth_integration.py`
- `tests/test_attach.py`
- `tests/conftest.py` only if a startup helper requires shared fixtures

Do not modify in this package:

- `src/agentmind/api/router.py`
- `src/agentmind/routing/pipeline.py`
- `src/agentmind/services/config_service.py`
- `src/agentmind/services/task_service.py`

## Strict Testing Rules

Every production change follows RED-GREEN:

1. Add or update a focused failing test.
2. Run that exact test and confirm it fails for the expected reason.
3. Implement the smallest production change.
4. Run the exact test and confirm it passes.
5. Run the package verification commands.
6. Commit the task.

Package verification commands:

```bash
pytest tests/test_startup.py -q
pytest tests/test_attach.py tests/test_auth_integration.py tests/test_panel_api.py -q
pytest -q
```

---

### Task 1: Add a startup module and token/bootstrap tests

**Files:**

- Create: `tests/test_startup.py`
- Create: `src/agentmind/startup.py`

- [ ] **Step 1: Write failing startup tests**

Create `tests/test_startup.py` with focused tests for token loading and app-state wiring:

```python
from pathlib import Path

import pytest

from agentmind.startup import AgentMindBootstrapper, load_or_generate_token


def test_load_or_generate_token_reuses_existing_token(tmp_path):
    data_home = tmp_path / "data-home"
    token_path = data_home / "config" / "auth.token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text("existing-token-012345678901234567890123", encoding="utf-8")

    token, is_new = load_or_generate_token(data_home)

    assert token == "existing-token-012345678901234567890123"
    assert is_new is False
    assert token_path.read_text(encoding="utf-8") == token


def test_bootstrapper_builds_app_and_keeps_state_local(tmp_path):
    data_home = tmp_path / "agentmind-home"
    config_dir = data_home / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "settings.yaml").write_text("feishu: {enabled: false}\n", encoding="utf-8")
    (config_dir / "agents.yaml").write_text("agents: []\n", encoding="utf-8")
    (config_dir / "routes.yaml").write_text("rules: []\n", encoding="utf-8")

    bootstrapper = AgentMindBootstrapper(port=8765, data_home=data_home)
    app = bootstrapper.create_app()

    assert app.title == "AgentMind"
    assert app.state.auth_token
    assert app.state.agent_registry is not None
    assert app.state.rule_engine is not None
    assert app.state.settings["feishu"]["enabled"] is False
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_startup.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentmind.startup'`.

- [ ] **Step 3: Implement the startup module**

Create `src/agentmind/startup.py`:

```python
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

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from agentmind.agents.discovery import discover_and_generate
from agentmind.agents.registry import AgentRegistry
from agentmind.config.defaults import generate_default_configs
from agentmind.core.rule_engine import RuleEngine
from agentmind.memory.workers.scheduler import MemoryWorkerScheduler
from agentmind.services.config_service import ConfigService
from agentmind.storage.db import DATA_HOME, initialize_data_directory, mark_timed_out_tasks_retriable

logger = logging.getLogger("agentmind")


def find_available_port(start_port: int = 8765, max_tries: int = 10) -> int:
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
    if not origin:
        return False
    try:
        parsed = urlparse(origin)
        return parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")
    except Exception:
        return False


@dataclass(slots=True)
class AgentMindBootstrapper:
    port: int
    data_home: Path = DATA_HOME

    def create_app(self) -> FastAPI:
        config_service = ConfigService(self.data_home / "config")
        settings = config_service.read_settings()
        agents_path = self.data_home / "config" / "agents.yaml"
        rule_path = self.data_home / "config" / "routes.yaml"
        agent_registry = AgentRegistry(agents_path)
        rule_engine = RuleEngine(rule_path, agent_registry=agent_registry)
        auth_token, token_is_new = load_or_generate_token(self.data_home)

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            await agent_registry.run_health_checks()
            mark_timed_out_tasks_retriable()
            health_task = asyncio.create_task(_periodic_health_check(agent_registry))
            memory_task = asyncio.create_task(_periodic_memory_cleanup())
            workspace_task = asyncio.create_task(_periodic_workspace_cleanup(self.data_home))
            stream_task = asyncio.create_task(_periodic_stream_cleanup())
            scheduler = MemoryWorkerScheduler()
            app.state.memory_scheduler = scheduler
            worker_task = asyncio.create_task(scheduler.start(settings))
            feishu_adapter = await _maybe_start_feishu(app, settings)
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
        app.state.agents_config_path = agents_path
        app.state.attach_registry = __import__("agentmind.api.attach_registry", fromlist=["AttachRegistry"]).AttachRegistry()
        app.state.routing_pipeline = __import__("agentmind.routing.pipeline", fromlist=["RoutingPipeline"]).RoutingPipeline(agent_registry, rule_engine)

        @app.middleware("http")
        async def auth_middleware(request, call_next):
            needs_auth = (
                request.method in ("POST", "PUT", "DELETE", "PATCH")
                or request.url.path.startswith("/panel/api/")
            )
            if needs_auth:
                origin = request.headers.get("origin", "")
                if origin and not is_local_origin(origin):
                    return JSONResponse(status_code=403, content={"error": "Forbidden origin"})
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

        self._register_app_routes(app, agent_registry, rule_engine)
        return app

    def _register_app_routes(self, app: FastAPI, agent_registry: AgentRegistry, rule_engine: RuleEngine) -> None:
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


async def _periodic_health_check(registry: AgentRegistry):
    while True:
        await asyncio.sleep(60)
        await registry.run_health_checks()


async def _periodic_memory_cleanup():
    from agentmind.storage.memory import cleanup_memory

    while True:
        await asyncio.sleep(3600)
        try:
            await cleanup_memory(retention_days=30)
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


async def _maybe_start_feishu(app: FastAPI, settings: dict[str, Any]):
    feishu_cfg = settings.get("feishu", {}) if isinstance(settings, dict) else {}
    if not (feishu_cfg.get("enabled") and feishu_cfg.get("app_id") and feishu_cfg.get("app_secret")):
        return None
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
        logger.info("飞书通道已启动")
        return feishu_adapter
    except Exception as e:
        logger.warning("飞书通道启动失败: %s", e)
        return None
```

- [ ] **Step 4: Run the focused tests**

Run:

```bash
pytest tests/test_startup.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentmind/startup.py tests/test_startup.py
git commit -m "feat: add startup bootstrap layer"
```

---

### Task 2: Slim main.py into a delegating entrypoint

**Files:**

- Modify: `src/agentmind/main.py`
- Modify: `tests/test_auth_integration.py`
- Modify: `tests/test_attach.py`

- [ ] **Step 1: Write a failing compatibility test for the public entrypoint**

Add or extend one lightweight test in `tests/test_auth_integration.py` or `tests/test_attach.py` so it proves `agentmind.main.create_app()` still returns a working app after the startup move:

```python
from agentmind.main import create_app


def test_create_app_keeps_public_contract(monkeypatch, tmp_path):
    monkeypatch.setattr("agentmind.main.DATA_HOME", tmp_path)
    app = create_app(0)

    assert app.state.agent_registry is not None
    assert app.state.rule_engine is not None
    assert app.state.auth_token
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_auth_integration.py tests/test_attach.py -q
```

Expected: FAIL if `main.py` still owns the old wiring and the new startup module is not yet delegated through the public entrypoint.

- [ ] **Step 3: Replace `main.py` with thin delegations**

Modify `src/agentmind/main.py` so it keeps only:

```python
from agentmind.startup import AgentMindBootstrapper, find_available_port


def create_app(port: int):
    return AgentMindBootstrapper(port=port, data_home=DATA_HOME).create_app()


async def async_main():
    initialize_data_directory()
    generate_default_configs()
    agents_path = DATA_HOME / "config" / "agents.yaml"
    logger.info("正在扫描已安装的 Agent...")
    await discover_and_generate(agents_path)
    port = find_available_port(8765)
    app = create_app(port)
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, loop="asyncio",
        log_level="warning",
    )
    server = uvicorn.Server(config)
    await server.serve()
```

Keep `main()` as the local loop runner and do not reintroduce lifecycle logic into `main.py`.

- [ ] **Step 4: Run the compatibility tests**

Run:

```bash
pytest tests/test_auth_integration.py tests/test_attach.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentmind/main.py tests/test_auth_integration.py tests/test_attach.py
git commit -m "refactor: delegate startup wiring out of main"
```

---

### Task 3: Run package verification and keep the startup boundary clean

**Files:**

- Modify: `tests/conftest.py` only if a startup helper needs fixture support

- [ ] **Step 1: Run the package verification commands**

Run:

```bash
pytest tests/test_startup.py -q
pytest tests/test_attach.py tests/test_auth_integration.py tests/test_panel_api.py -q
pytest -q
```

Expected:

```text
all targeted tests pass
full suite remains green
```

- [ ] **Step 2: Check for startup creep**

Confirm `main.py` still does not own:

```text
Feishu startup logic
memory worker creation
periodic cleanup loops
auth token file management
panel HTML rendering
app.state wiring beyond delegation
```

- [ ] **Step 3: Commit the package**

```bash
git add src/agentmind/startup.py src/agentmind/main.py tests/test_startup.py tests/test_auth_integration.py tests/test_attach.py
git commit -m "refactor: converge app startup"
```
