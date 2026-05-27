"""控制面板 API 严格测试 — 每个端点至少 happy path + 1 edge case"""
import json
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.staticfiles import StaticFiles

from agentmind.agents.registry import AgentRegistry
from agentmind.core.rule_engine import RuleEngine
from agentmind.storage.db import initialize_data_directory


def make_panel_app(tmp_dir):
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("agentmind.storage.db.DATA_DIR", tmp_dir / "data")
    monkeypatch.setattr("agentmind.storage.db.DATA_HOME", tmp_dir)
    monkeypatch.setattr("agentmind.storage.db.CONFIG_DIR", tmp_dir / "config")
    monkeypatch.setattr("agentmind.storage.db.LOGS_DIR", tmp_dir / "logs")
    monkeypatch.setattr("agentmind.storage.memory.DATA_DIR", tmp_dir / "data")
    monkeypatch.setattr("agentmind.storage.memory.CONFIG_DIR", tmp_dir / "config")
    monkeypatch.setattr("agentmind.panel.server.CONFIG_DIR", tmp_dir / "config")
    monkeypatch.setattr("agentmind.api.orchestration.CONFIG_DIR", tmp_dir / "config")
    monkeypatch.setattr("agentmind.storage.embedding.has_local_embedding", lambda: False)
    (tmp_dir / "data" / "results").mkdir(parents=True, exist_ok=True)
    (tmp_dir / "config").mkdir(parents=True, exist_ok=True)
    # 确保 settings.yaml 存在，避免 write_text 时目录不存在
    settings_path = tmp_dir / "config" / "settings.yaml"
    if not settings_path.exists():
        settings_path.write_text("memory:\n  max_entries: 10000\nembedding:\n  enabled: false\n")
    initialize_data_directory()

    agents_config = {
        "agents": [
            {"id": "mock_echo", "name": "Mock Echo", "type": "cli", "tags": ["code"], "enabled": True, "timeout": 5,
             "config": {"command": "echo done", "health_check": "echo ok"}},
        ]
    }
    routes_config = {"rules": []}
    agents_path = tmp_dir / "config" / "agents.yaml"
    routes_path = tmp_dir / "config" / "routes.yaml"
    agents_path.write_text(yaml.dump(agents_config, allow_unicode=True), encoding="utf-8")
    routes_path.write_text(yaml.dump(routes_config, allow_unicode=True), encoding="utf-8")

    registry = AgentRegistry(agents_path)
    rule_engine = RuleEngine(routes_path, agent_registry=registry)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(lifespan=lifespan)
    app.state.agent_registry = registry
    app.state.rule_engine = rule_engine
    app.state.agents_config_path = agents_path

    from agentmind.api.agents import router as agents_router
    from agentmind.api.router import router as route_router
    from agentmind.api.orchestration import router as orch_router
    from agentmind.panel import create_panel_router

    app.include_router(agents_router, prefix="/v1")
    app.include_router(route_router, prefix="/v1")
    app.include_router(orch_router, prefix="/v1")
    app.include_router(create_panel_router(), prefix="/panel/api")

    static_dir = Path(__file__).parent.parent / "src" / "agentmind" / "panel" / "static"
    if static_dir.exists():
        app.mount("/panel", StaticFiles(directory=str(static_dir), html=True), name="panel")

    for ex in registry.executors.values():
        ex.is_healthy = True

    return app, monkeypatch


def _client(tmp_dir):
    return TestClient(make_panel_app(tmp_dir)[0])


class TestPanelAPI:
    def test_tasks_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/tasks/stats")
                assert resp.status_code == 200
                data = resp.json()
                assert "total" in data
            finally:
                mp.undo()

    def test_agents_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/agents")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["agents"]) >= 1
                agent = data["agents"][0]
                assert "id" in agent
                assert "healthy" in agent
            finally:
                mp.undo()

    def test_agents_endpoint_uses_agent_control_service(self):
        calls = []

        class FakeAgentControlService:
            def __init__(
                self,
                agent_registry,
                config_service=None,
                agent_config_service=None,
                config_dir=None,
            ):
                calls.append({
                    "agent_registry": agent_registry,
                    "config_service": config_service,
                    "agent_config_service": agent_config_service,
                    "config_dir": config_dir,
                })

            def list_agents(self):
                calls.append(("list_agents",))
                return [{"id": "from_service", "healthy": True}]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            mp.setattr(
                "agentmind.panel.server.AgentControlService",
                FakeAgentControlService,
                raising=False,
            )
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/agents")
                assert resp.status_code == 200
                assert resp.json() == {"agents": [{"id": "from_service", "healthy": True}]}
                assert calls[0]["agent_registry"] is app.state.agent_registry
                assert calls[0]["config_service"] is not None
                assert calls[0]["agent_config_service"] is not None
                assert calls[0]["config_dir"] is None
                assert calls[1] == ("list_agents",)
            finally:
                mp.undo()

    def test_agent_capabilities_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/agents/capabilities")
                assert resp.status_code == 200
                data = resp.json()
                assert "capabilities" in data
                profile = data["capabilities"][0]
                assert profile["agent_id"] == "mock_echo"
                assert profile["protocol"] == "cli"
                assert profile["healthy"] is True
                assert "success_rate" in profile
            finally:
                mp.undo()

    def test_agent_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.post("/panel/api/agents/mock_echo/restart")
                assert resp.status_code == 200
                assert resp.json()["agent_id"] == "mock_echo"
            finally:
                mp.undo()

    def test_agent_restart_404(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.post("/panel/api/agents/nonexistent/restart")
                assert resp.status_code == 404
            finally:
                mp.undo()

    def test_strategy_status_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/routing/strategies")
                assert resp.status_code == 200
                data = resp.json()
                core = [s["name"] for s in data["strategies"] if s["kind"] == "core"]
                assert core == ["explicit", "rule_engine", "llm_routing", "signal_scoring"]
                assert any(
                    s["name"] == "memory_recall" and s["kind"] == "auxiliary"
                    for s in data["strategies"]
                )
            finally:
                mp.undo()

    def test_audit_events_endpoint_uses_audit_service(self):
        calls = []

        class FakeAuditService:
            async def query_events(self, **kwargs):
                calls.append(kwargs)
                return [{"event_id": "e1", "module": "config", "action": "update"}]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            mp.setattr("agentmind.panel.server.AuditService", FakeAuditService, raising=False)
            client = TestClient(app)
            try:
                resp = client.get(
                    "/panel/api/audit/events"
                    "?module=config&action=update&agent_id=a1"
                    "&risk_level=medium&trace_id=t1&actor=system&limit=7"
                )
                assert resp.status_code == 200
                assert resp.json() == {
                    "events": [{"event_id": "e1", "module": "config", "action": "update"}]
                }
                assert calls == [{
                    "limit": 7,
                    "module": "config",
                    "action": "update",
                    "agent_id": "a1",
                    "risk_level": "medium",
                    "trace_id": "t1",
                    "actor": "system",
                }]
            finally:
                mp.undo()

    def test_routing_explanation_endpoint_uses_service(self):
        calls = []

        class FakeRoutingExplanationService:
            def __init__(
                self,
                *,
                trace_service=None,
                audit_service=None,
                capability_registry=None,
                strategy_manager=None,
            ):
                calls.append({
                    "trace_service": trace_service,
                    "audit_service": audit_service,
                    "capability_registry": capability_registry,
                    "strategy_manager": strategy_manager,
                })

            async def explain(self, trace_id):
                calls.append({"trace_id": trace_id})
                return {"trace_id": trace_id, "found": True, "summary": "explained"}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            mp.setattr(
                "agentmind.panel.server.RoutingExplanationService",
                FakeRoutingExplanationService,
                raising=False,
            )
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/routing/explanations/t1")
                assert resp.status_code == 200
                assert resp.json() == {
                    "trace_id": "t1",
                    "found": True,
                    "summary": "explained",
                }
                assert calls[0]["trace_service"] is not None
                assert calls[0]["audit_service"] is not None
                assert calls[0]["capability_registry"] is not None
                assert calls[0]["strategy_manager"] is not None
                assert calls[1] == {"trace_id": "t1"}
            finally:
                mp.undo()

    def test_task_explanation_endpoint_uses_service(self):
        calls = []

        class FakeTaskExplanationService:
            def __init__(
                self,
                *,
                task_service=None,
                routing_explanation_service=None,
                audit_service=None,
            ):
                calls.append({
                    "task_service": task_service,
                    "routing_explanation_service": routing_explanation_service,
                    "audit_service": audit_service,
                })

            async def explain(self, trace_id):
                calls.append({"trace_id": trace_id})
                return {
                    "trace_id": trace_id,
                    "found": True,
                    "status": "failed",
                    "stage": "execution",
                }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            mp.setattr(
                "agentmind.panel.server.TaskExplanationService",
                FakeTaskExplanationService,
                raising=False,
            )
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/tasks/t1/explanation")
                assert resp.status_code == 200
                assert resp.json() == {
                    "trace_id": "t1",
                    "found": True,
                    "status": "failed",
                    "stage": "execution",
                }
                assert calls[0]["task_service"] is not None
                assert calls[0]["routing_explanation_service"] is not None
                assert calls[0]["audit_service"] is not None
                assert calls[1] == {"trace_id": "t1"}
            finally:
                mp.undo()

    def test_task_read_endpoints_use_task_service(self):
        calls = []

        class FakeTaskService:
            async def query_tasks(self, limit=20, offset=0, status=None):
                calls.append(("query", limit, offset, status))
                return [{"trace_id": "t1", "status": status or "completed"}]

            async def get_task_stats(self):
                calls.append(("stats",))
                return {"total": 1, "completed": 1}

            async def get_recent_errors(self, limit=5):
                calls.append(("errors", limit))
                return [{"trace_id": "e1", "error_message": "boom"}]

            async def get_task_detail(self, trace_id):
                calls.append(("detail", trace_id))
                return {"trace_id": trace_id, "status": "completed"}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            mp.setattr("agentmind.panel.server.TaskService", FakeTaskService, raising=False)
            client = TestClient(app)
            try:
                assert client.get("/panel/api/tasks?limit=3&offset=2&status=failed").json() == {
                    "tasks": [{"trace_id": "t1", "status": "failed"}]
                }
                assert client.get("/panel/api/tasks/stats").json() == {
                    "total": 1,
                    "completed": 1,
                }
                assert client.get("/panel/api/tasks/recent-errors?limit=4").json() == {
                    "errors": [{"trace_id": "e1", "error_message": "boom"}]
                }
                assert client.get("/panel/api/tasks/t1").json() == {
                    "trace_id": "t1",
                    "status": "completed",
                }
                assert calls == [
                    ("query", 3, 2, "failed"),
                    ("stats",),
                    ("errors", 4),
                    ("detail", "t1"),
                ]
            finally:
                mp.undo()

    def test_control_overview_endpoint_uses_service(self):
        calls = []

        class FakeControlPlaneOverviewService:
            def __init__(
                self,
                *,
                task_service=None,
                capability_registry=None,
                strategy_manager=None,
                audit_service=None,
            ):
                calls.append({
                    "task_service": task_service,
                    "capability_registry": capability_registry,
                    "strategy_manager": strategy_manager,
                    "audit_service": audit_service,
                })

            async def overview(self):
                calls.append(("overview",))
                return {"status": "healthy", "summary": {"agents_total": 1}}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            mp.setattr(
                "agentmind.panel.server.ControlPlaneOverviewService",
                FakeControlPlaneOverviewService,
                raising=False,
            )
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/control/overview")
                assert resp.status_code == 200
                assert resp.json() == {"status": "healthy", "summary": {"agents_total": 1}}
                assert calls[0]["task_service"] is not None
                assert calls[0]["capability_registry"] is not None
                assert calls[0]["strategy_manager"] is not None
                assert calls[0]["audit_service"] is not None
                assert calls[1] == ("overview",)
            finally:
                mp.undo()

    def test_service_status_uses_control_plane_overview_service(self):
        calls = []

        class FakeControlPlaneOverviewService:
            def __init__(self, **kwargs):
                calls.append(kwargs)

            async def service_status(self):
                calls.append(("service_status",))
                return {
                    "agents_total": 2,
                    "agents_healthy": 1,
                    "tasks_total": 3,
                    "tasks_completed": 2,
                    "tasks_failed": 1,
                    "avg_execution_time_ms": 5,
                }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            mp.setattr(
                "agentmind.panel.server.ControlPlaneOverviewService",
                FakeControlPlaneOverviewService,
                raising=False,
            )
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/service/status")
                assert resp.status_code == 200
                assert resp.json() == {
                    "agents_total": 2,
                    "agents_healthy": 1,
                    "tasks_total": 3,
                    "tasks_completed": 2,
                    "tasks_failed": 1,
                    "avg_execution_time_ms": 5,
                }
                assert calls[0]["task_service"] is not None
                assert calls[0]["capability_registry"] is not None
                assert calls[0]["strategy_manager"] is not None
                assert calls[0]["audit_service"] is not None
                assert calls[1] == ("service_status",)
            finally:
                mp.undo()

    def test_agent_toggle(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.post("/panel/api/agents/mock_echo/toggle")
                assert resp.status_code == 200
                data = resp.json()
                assert data["agent_id"] == "mock_echo"
                assert data["enabled"] == False
            finally:
                mp.undo()

    def test_agent_add(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.post("/panel/api/agents/add", json={
                    "id": "new_agent", "name": "New Agent", "command": "echo test",
                })
                assert resp.status_code == 200
                assert resp.json()["ok"] == True
                # 验证已存在于列表中
                resp2 = client.get("/panel/api/agents")
                assert any(a["id"] == "new_agent" for a in resp2.json()["agents"])
            finally:
                mp.undo()

    def test_service_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/service/status")
                assert resp.status_code == 200
                data = resp.json()
                assert "agents_total" in data
                assert "agents_healthy" in data
            finally:
                mp.undo()


# ═══════════════════════════════════
# 任务端点
# ═══════════════════════════════════

class TestTasks:
    def test_list_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/tasks")
                assert resp.status_code == 200
                assert "tasks" in resp.json()
            finally:
                mp.undo()

    def test_recent_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/tasks/recent-errors")
                assert resp.status_code == 200
                assert "errors" in resp.json()
            finally:
                mp.undo()

    def test_task_detail_404(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/tasks/nonexistent-id")
                assert resp.status_code == 404
            finally:
                mp.undo()


# ═══════════════════════════════════
# 记忆端点
# ═══════════════════════════════════

class TestMemory:
    def test_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/memory/search")
                assert resp.status_code == 200
                assert "memories" in resp.json()
            finally:
                mp.undo()

    def test_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/memory/stats")
                assert resp.status_code == 200
                data = resp.json()
                assert "total" in data
            finally:
                mp.undo()

    def test_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.delete("/panel/api/memory/not-exist-id")
                assert resp.status_code == 200
                assert resp.json()["ok"] == True
            finally:
                mp.undo()

    def test_panel_memory_delete_uses_memory_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            calls = []

            class FakeMemoryService:
                async def delete_memory(self, memory_id):
                    calls.append(memory_id)
                    return True

            mp.setattr("agentmind.panel.server.MemoryService", FakeMemoryService, raising=False)
            try:
                resp = client.delete("/panel/api/memory/m-panel-delete")
                assert resp.status_code == 200
                assert resp.json()["ok"] is True
                assert calls == ["m-panel-delete"]
            finally:
                mp.undo()

    def test_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.post("/panel/api/memory/cleanup?retention_days=30")
                assert resp.status_code == 200
                assert "deleted" in resp.json()
            finally:
                mp.undo()


# ═══════════════════════════════════
# 飞书端点
# ═══════════════════════════════════

class TestFeishu:
    def test_get_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/feishu/config")
                assert resp.status_code == 200
                assert "app_id" in resp.json()
            finally:
                mp.undo()

    def test_save_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.post("/panel/api/feishu/config", json={
                    "enabled": True, "app_id": "test", "app_secret": "test",
                })
                assert resp.status_code == 200
                assert resp.json()["ok"] == True
            finally:
                mp.undo()

    def test_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/feishu/status")
                assert resp.status_code == 200
                data = resp.json()
                assert "connected" in data
            finally:
                mp.undo()


# ═══════════════════════════════════
# 设置/连接器/会话
# ═══════════════════════════════════

class TestSettings:
    def test_get(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/settings")
                assert resp.status_code == 200
                data = resp.json()
                assert "memory" in data
                assert "embedding" in data
            finally:
                mp.undo()

    def test_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.post("/panel/api/settings", json={
                    "memory": {"max_entries": 500},
                })
                assert resp.status_code == 200
                assert resp.json()["ok"] == True
                # 验证读取
                resp2 = client.get("/panel/api/settings")
                assert resp2.json()["memory"]["max_entries"] == 500
            finally:
                mp.undo()


class TestEmbeddingStatus:
    def test_status_disabled(self):
        """embedding 未启用时返回空状态"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/embedding/status")
                assert resp.status_code == 200
                data = resp.json()
                assert data["enabled"] == False
                assert data["summary"] == "未配置"
            finally:
                mp.undo()

    def test_status_with_external_api(self):
        """外部 API 已配置时返回正确状态"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            # 写入启用了外部 API 的 settings
            (tmp_dir / "config").mkdir(parents=True, exist_ok=True)
            settings_path = tmp_dir / "config" / "settings.yaml"
            settings_path.write_text(
                yaml.dump({
                    "embedding": {
                        "enabled": True,
                        "endpoint": "https://api.example.com/embeddings",
                        "api_key": "sk-test",
                        "model": "test-model",
                        "dimension": 768,
                    }
                }), encoding="utf-8"
            )
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/embedding/status")
                assert resp.status_code == 200
                data = resp.json()
                assert data["enabled"] == True
                assert data["has_external_api"] == True
                assert data["summary"] == "外部 API 已配置"
            finally:
                mp.undo()

    def test_status_no_source(self):
        """无 endpoint 且无本地模型时 summary 为未配置"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            (tmp_dir / "config").mkdir(parents=True, exist_ok=True)
            settings_path = tmp_dir / "config" / "settings.yaml"
            settings_path.write_text(
                yaml.dump({
                    "embedding": {
                        "enabled": True,
                        "endpoint": "",
                        "api_key": "",
                    }
                }), encoding="utf-8"
            )
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/embedding/status")
                assert resp.status_code == 200
                data = resp.json()
                assert data["enabled"] == True
                assert data["has_external_api"] == False
                assert data["summary"] == "未配置"
            finally:
                mp.undo()


class TestMetaSettings:
    def test_get_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            (tmp_dir / "config").mkdir(parents=True, exist_ok=True)
            settings_path = tmp_dir / "config" / "settings.yaml"
            settings_path.write_text(
                yaml.dump({"core_llm": {"enabled": False, "endpoint": "", "model": ""}}), encoding="utf-8"
            )
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/settings")
                assert resp.status_code == 200
                data = resp.json()
                assert "meta" in data
                assert data["meta"]["enabled"] == False
            finally:
                mp.undo()

    def test_save_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.post("/panel/api/settings", json={
                    "meta": {"enabled": True, "endpoint": "https://api.example.com", "api_key": "sk-test", "model": "gpt-4"},
                })
                assert resp.status_code == 200
                assert resp.json()["ok"] == True
                resp2 = client.get("/panel/api/settings")
                assert resp2.json()["meta"]["enabled"] == True
                assert resp2.json()["meta"]["model"] == "gpt-4"
            finally:
                mp.undo()


class TestConnectors:
    def test_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/connectors")
                assert resp.status_code == 200
                assert "connectors" in resp.json()
                assert len(resp.json()["connectors"]) >= 5
            finally:
                mp.undo()


class TestSessions:
    def test_active_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/sessions")
                assert resp.status_code == 200
                data = resp.json()
                assert "discussions" in data
                assert "executing_tasks" in data
            finally:
                mp.undo()


# ═══════════════════════════════════
# 编排端点
# ═══════════════════════════════════

class TestOrchestrationAPI:
    def test_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.post("/v1/orchestrations/save", json={
                    "plan_id": "test-plan", "name": "测试计划",
                    "trigger_words": ["测试"], "steps": [],
                })
                assert resp.status_code == 200
                assert resp.json()["ok"] == True
            finally:
                mp.undo()

    def test_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/v1/orchestrations/list")
                assert resp.status_code == 200
                assert "plans" in resp.json()
            finally:
                mp.undo()

    def test_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                # 先存一条
                client.post("/v1/orchestrations/save", json={
                    "plan_id": "to-delete", "name": "待删", "trigger_words": [], "steps": [],
                })
                # 再删
                resp = client.delete("/v1/orchestrations/to-delete")
                assert resp.status_code == 200
                assert resp.json()["ok"] == True
                # 验证已删
                resp2 = client.get("/v1/orchestrations/list")
                assert not any(p["plan_id"] == "to-delete" for p in resp2.json()["plans"])
            finally:
                mp.undo()


class TestServiceMetrics:
    def test_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/service/metrics")
                assert resp.status_code == 200
                data = resp.json()
                assert "latency_ms" in data or "throughput_1h" in data
            finally:
                mp.undo()


class TestPanelConfigServiceUsage:
    def test_agent_add_uses_agent_control_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            calls = []

            class FakeAgentControlService:
                def __init__(self, *args, **kwargs):
                    calls.append(("init", args, kwargs))

                def add_cli_agent(self, agent_id, name, command, tags):
                    calls.append(("add", agent_id, name, command, tags))
                    return {"ok": True}

            try:
                mp.setattr("agentmind.panel.server.AgentControlService", FakeAgentControlService, raising=False)
                resp = client.post("/panel/api/agents/add", json={
                    "id": "new_agent",
                    "name": "New Agent",
                    "command": "echo ok",
                    "tags": "general,code",
                })
                assert resp.status_code == 200
                assert resp.json() == {"ok": True}
                assert calls[1] == ("add", "new_agent", "New Agent", "echo ok", ["general", "code"])
            finally:
                mp.undo()

    def test_agent_restart_uses_agent_control_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            calls = []

            class FakeAgentControlService:
                def __init__(self, *args, **kwargs):
                    calls.append(("init", args, kwargs))

                async def restart_agent(self, agent_id):
                    calls.append(("restart", agent_id))
                    return {"agent_id": agent_id, "healthy": False}

            try:
                mp.setattr("agentmind.panel.server.AgentControlService", FakeAgentControlService, raising=False)
                resp = client.post("/panel/api/agents/mock_echo/restart")
                assert resp.status_code == 200
                assert resp.json() == {"agent_id": "mock_echo", "healthy": False}
                assert calls[1] == ("restart", "mock_echo")
            finally:
                mp.undo()

    def test_agent_tags_uses_agent_control_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            calls = []

            class FakeAgentControlService:
                def __init__(self, *args, **kwargs):
                    calls.append(("init", args, kwargs))

                def update_tags(self, agent_id, tags):
                    calls.append(("tags", agent_id, tags))
                    return {"ok": True, "tags": tags}

            try:
                mp.setattr("agentmind.panel.server.AgentControlService", FakeAgentControlService, raising=False)
                resp = client.post("/panel/api/agents/mock_echo/tags", json={"tags": ["new"]})
                assert resp.status_code == 200
                assert resp.json() == {"ok": True, "tags": ["new"]}
                assert calls[1] == ("tags", "mock_echo", ["new"])
            finally:
                mp.undo()

    def test_agent_toggle_uses_agent_control_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            calls = []

            class FakeAgentControlService:
                def __init__(self, *args, **kwargs):
                    calls.append(("init", args, kwargs))

                def toggle_enabled(self, agent_id):
                    calls.append(("toggle", agent_id))
                    return {"agent_id": agent_id, "enabled": False}

            try:
                mp.setattr("agentmind.panel.server.AgentControlService", FakeAgentControlService, raising=False)
                resp = client.post("/panel/api/agents/mock_echo/toggle")
                assert resp.status_code == 200
                assert resp.json() == {"agent_id": "mock_echo", "enabled": False}
                assert calls[1] == ("toggle", "mock_echo")
            finally:
                mp.undo()

    def test_settings_save_uses_config_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            calls = []

            class FakeConfigService:
                def __init__(self, config_dir=None):
                    self.config_dir = config_dir

                def update_settings_sections(self, sections):
                    calls.append(sections)
                    return {"memory": {"max_entries": 321}}

            try:
                mp.setattr("agentmind.panel.server.ConfigService", FakeConfigService)
                resp = client.post("/panel/api/settings", json={
                    "memory": {"max_entries": 321},
                })
                assert resp.status_code == 200
                assert resp.json()["ok"] is True
                assert calls == [{"memory": {"max_entries": 321}}]
            finally:
                mp.undo()

    def test_rules_save_uses_config_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            writes = []

            class FakeConfigService:
                def __init__(self, config_dir=None):
                    self.config_dir = config_dir

                def read_routes(self):
                    return {"rules": []}

                def write_routes(self, data):
                    writes.append(data)
                    return data

            try:
                mp.setattr("agentmind.panel.server.ConfigService", FakeConfigService)
                resp = client.post("/panel/api/rules", json={
                    "name": "route-a",
                    "type": "keyword",
                    "patterns": ["hello"],
                    "target_tags": ["general"],
                    "priority": 10,
                    "tags": ["demo"],
                })
                assert resp.status_code == 200
                assert resp.json()["ok"] is True
                assert writes == [{
                    "rules": [{
                        "name": "route-a",
                        "type": "keyword",
                        "patterns": ["hello"],
                        "target_tags": ["general"],
                        "priority": 10,
                        "tags": ["demo"],
                    }]
                }]
            finally:
                mp.undo()
