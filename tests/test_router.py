import json
import tempfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from agentmind.agents.registry import AgentRegistry
from agentmind.core.rule_engine import RuleEngine
from agentmind.storage.db import initialize_data_directory


def make_test_app(tmp_dir):
    """创建测试用 app，仅用 mock echo Agent，不依赖真实环境"""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("agentmind.storage.db.DATA_DIR", tmp_dir / "data")
    monkeypatch.setattr("agentmind.storage.db.DATA_HOME", tmp_dir)
    monkeypatch.setattr("agentmind.storage.db.CONFIG_DIR", tmp_dir / "config")
    monkeypatch.setattr("agentmind.storage.db.LOGS_DIR", tmp_dir / "logs")
    (tmp_dir / "data" / "results").mkdir(parents=True, exist_ok=True)
    (tmp_dir / "config").mkdir(parents=True, exist_ok=True)
    initialize_data_directory()

    agents_config = {
        "agents": [
            {"id": "mock_echo", "name": "Mock Echo", "type": "cli", "tags": ["code", "general"], "enabled": True, "timeout": 5,
             "config": {"command": "echo done", "health_check": "echo ok"}},
        ]
    }
    routes_config = {
        "rules": [
            {"name": "code_kw", "type": "keyword", "patterns": ["写一个", "代码"], "target_tags": ["code"], "priority": 10, "tags": ["code"]},
        ]
    }
    agents_path = tmp_dir / "config" / "agents.yaml"
    routes_path = tmp_dir / "config" / "routes.yaml"
    agents_path.write_text(yaml.dump(agents_config, allow_unicode=True), encoding="utf-8")
    routes_path.write_text(yaml.dump(routes_config, allow_unicode=True), encoding="utf-8")

    # 直接构建 app，跳过 discover_and_generate
    from contextlib import asynccontextmanager
    import asyncio
    from fastapi import FastAPI

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
    app.include_router(agents_router, prefix="/v1")
    app.include_router(route_router, prefix="/v1")

    # 标记 agent 为健康
    for ex in registry.executors.values():
        ex.is_healthy = True

    return app, monkeypatch


class TestRouteNonStream:
    def test_non_stream_returns_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_test_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.post("/v1/route", json={"message": "写一个函数", "stream": False})
                assert resp.status_code == 200
                assert resp.headers["content-type"] == "application/json"
                data = resp.json()
                assert "trace_id" in data
                assert data["agent_id"] == "mock_echo"
            finally:
                mp.undo()

    def test_non_stream_contains_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_test_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.post("/v1/route", json={"message": "写一个函数", "stream": False})
                data = resp.json()
                assert "result" in data
                assert "execution_time_ms" in data
            finally:
                mp.undo()


class TestRouteStream:
    def test_stream_returns_sse(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_test_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.post("/v1/route", json={"message": "写一个函数", "stream": True})
                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers["content-type"]
            finally:
                mp.undo()

    def test_stream_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_test_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.post("/v1/route", json={"message": "写一个函数", "stream": True})
                body = resp.text
                assert "routed" in body
                assert "completed" in body or "error" in body
            finally:
                mp.undo()


class TestRouteNoAgent:
    def test_no_healthy_agent_returns_503(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_test_app(tmp_dir)
            for ex in app.state.agent_registry.executors.values():
                ex.is_healthy = False
            client = TestClient(app)
            try:
                resp = client.post("/v1/route", json={"message": "写一个函数", "stream": False})
                assert resp.status_code == 503
                assert "没有可用" in resp.json()["error"]
            finally:
                mp.undo()


class TestRoutePipelineEdgeCases:
    """6 步流水线边界案例和失败案例"""

    def test_explicit_prefix_match(self):
        """① @agentname 直接命中"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_test_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.post("/v1/route", json={"message": "@mock_echo 写代码", "stream": False})
                assert resp.status_code == 200
                assert resp.json()["agent_id"] == "mock_echo"
            finally:
                mp.undo()

    def test_explicit_prefix_nonexistent(self):
        """① @不存在的agent 被忽略，继续后续步骤"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_test_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.post("/v1/route", json={"message": "@nonexistent 写一个函数", "stream": False})
                assert resp.status_code == 200
                assert resp.json()["agent_id"] == "mock_echo"
            finally:
                mp.undo()

    def test_security_intercept_api_key(self):
        """② 检测到 API Key → 降级到本地 Agent"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_test_app(tmp_dir)
            # 写入包含 local/cloud 两种 Agent 的配置并 reload
            new_config = {
                "agents": [
                    {"id": "cloud_agent", "name": "Cloud", "type": "cli", "tags": ["code"],
                     "security_level": "cloud", "enabled": True, "timeout": 5,
                     "config": {"command": "echo cloud", "health_check": "echo ok"}},
                    {"id": "local_agent", "name": "Local", "type": "cli", "tags": ["general"],
                     "security_level": "local", "enabled": True, "timeout": 5,
                     "config": {"command": "echo local", "health_check": "echo ok"}},
                ]
            }
            agents_path = tmp_dir / "config" / "agents.yaml"
            agents_path.write_text(yaml.dump(new_config, allow_unicode=True), encoding="utf-8")
            import asyncio
            asyncio.run(app.state.agent_registry.reload(agents_path))
            for ex in app.state.agent_registry.executors.values():
                ex.is_healthy = True
            client = TestClient(app)
            try:
                resp = client.post("/v1/route", json={
                    "message": "我的key是 sk-abc123def456ghi789jkl012mno345pqr678stu",
                    "stream": False,
                })
                assert resp.status_code == 200
                assert resp.json()["agent_id"] == "local_agent"
            finally:
                mp.undo()

    def test_security_intercept_no_local_continues(self):
        """② 无本地 Agent 且敏感内容时，应拒绝而非泄露到云端"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_test_app(tmp_dir)
            # 只有 cloud agent，没有 local
            new_config = {
                "agents": [
                    {"id": "cloud_only", "name": "Cloud Only", "type": "cli", "tags": ["code", "general"],
                     "security_level": "cloud", "enabled": True, "timeout": 5,
                     "config": {"command": "echo cloud", "health_check": "echo ok"}},
                ]
            }
            agents_path = tmp_dir / "config" / "agents.yaml"
            agents_path.write_text(yaml.dump(new_config, allow_unicode=True), encoding="utf-8")
            import asyncio
            asyncio.run(app.state.agent_registry.reload(agents_path))
            for ex in app.state.agent_registry.executors.values():
                ex.is_healthy = True
            client = TestClient(app)
            try:
                resp = client.post("/v1/route", json={
                    "message": "api_key='sk-abc123def456ghi789jkl012mno345pqr678stu'",
                    "stream": False,
                })
                # 敏感内容 + 无本地 Agent → 应拒绝（503 或空 agent_id）
                data = resp.json()
                assert resp.status_code in (503, 200)
                assert data.get("agent_id", "") in ("", None) or "error" in data
            finally:
                mp.undo()

    def test_rule_engine_no_match_goes_to_fallback(self):
        """规则引擎无匹配 → SignalScoring 兜底返回健康 Agent"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_test_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.post("/v1/route", json={"message": "与任何规则都不匹配的消息", "stream": False})
                assert resp.status_code == 200
                data = resp.json()
                assert data["agent_id"] == "mock_echo"
            finally:
                mp.undo()

    def test_signal_scoring_picks_low_cost(self):
        """SignalScoring 策略：低成本 Agent 得分更高"""
        from agentmind.routing.strategies.signal_scoring import SignalScoringStrategy
        from agentmind.agents.base import AgentCapability
        from agentmind.agents.cli_executor import CLIExecutor

        cap_cheap = AgentCapability(id="cheap", name="Cheap", type="cli", tags=[],
                                    estimated_cost=0.001, avg_latency=1.0)
        cap_costly = AgentCapability(id="costly", name="Costly", type="cli", tags=[],
                                     estimated_cost=0.5, avg_latency=10.0)

        cheap_ex = CLIExecutor(cap_cheap)
        cheap_ex.is_healthy = True
        costly_ex = CLIExecutor(cap_costly)
        costly_ex.is_healthy = True

        class _FakeReg:
            executors = {"cheap": cheap_ex, "costly": costly_ex}
            def get_executor(self, aid):
                return self.executors.get(aid)

        strategy = SignalScoringStrategy(_FakeReg())
        result = strategy._score_best(["cheap", "costly"], is_retry=False)
        assert result == "cheap"

    def test_explicit_prefix_masks_keyword_match(self):
        """① 优先级最高：@agent 即使有匹配关键词也走显式前缀"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_test_app(tmp_dir)
            client = TestClient(app)
            try:
                # "写一个函数" 正常情况被③ keyword匹配到 mock_echo
                # 但加了 @mock_echo 走①显式前缀，结果相同但路径不同
                resp = client.post("/v1/route", json={"message": "@mock_echo 写一个函数", "stream": False})
                assert resp.status_code == 200
                assert resp.json()["agent_id"] == "mock_echo"
            finally:
                mp.undo()


class TestContextInjection:
    def test_context_injection_with_user_id(self):
        """有 user_id 时，路由注入上下文并写入带 user tag 的记忆"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_test_app(tmp_dir)
            # 确保 memory 模块也指向测试目录
            mp.setattr("agentmind.storage.memory.DATA_DIR", tmp_dir / "data")
            mp.setattr("agentmind.storage.memory.CONFIG_DIR", tmp_dir / "config")
            client = TestClient(app)
            try:
                resp = client.post("/v1/route", json={
                    "message": "写一个登录接口",
                    "user_id": "test_user_ctx",
                    "stream": False,
                })
                assert resp.status_code == 200
                data = resp.json()
                assert "trace_id" in data
                trace_id = data["trace_id"]

                import asyncio
                from agentmind.storage.memory import search_memory
                results = asyncio.run(search_memory(user_id="test_user_ctx", limit=5))
                assert any(r["source_task_id"] == trace_id for r in results)
            finally:
                mp.undo()

    def test_context_injection_no_user_id(self):
        """无 user_id 时不崩溃，正常路由"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_test_app(tmp_dir)
            mp.setattr("agentmind.storage.memory.DATA_DIR", tmp_dir / "data")
            mp.setattr("agentmind.storage.memory.CONFIG_DIR", tmp_dir / "config")
            client = TestClient(app)
            try:
                resp = client.post("/v1/route", json={
                    "message": "搜索最新的Python新闻",
                    "stream": False,
                })
                assert resp.status_code == 200
                assert "trace_id" in resp.json()
            finally:
                mp.undo()

    def test_consecutive_messages_share_context(self):
        """连续两条消息：第二条能找到第一条的记忆"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_test_app(tmp_dir)
            mp.setattr("agentmind.storage.memory.DATA_DIR", tmp_dir / "data")
            mp.setattr("agentmind.storage.memory.CONFIG_DIR", tmp_dir / "config")
            client = TestClient(app)
            try:
                # 第一条消息
                resp1 = client.post("/v1/route", json={
                    "message": "帮我写一个登录接口",
                    "user_id": "ou_ctx_chained",
                    "stream": False,
                })
                assert resp1.status_code == 200

                # 第二条消息
                resp2 = client.post("/v1/route", json={
                    "message": "加上 JWT 校验",
                    "user_id": "ou_ctx_chained",
                    "stream": False,
                })
                assert resp2.status_code == 200

                # 验证两条记忆都存在
                import asyncio
                from agentmind.storage.memory import search_memory
                results = asyncio.run(search_memory(user_id="ou_ctx_chained", limit=10))
                assert len(results) >= 2
            finally:
                mp.undo()

    def test_cross_user_isolation(self):
        """不同用户消息互不干扰"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_test_app(tmp_dir)
            mp.setattr("agentmind.storage.memory.DATA_DIR", tmp_dir / "data")
            mp.setattr("agentmind.storage.memory.CONFIG_DIR", tmp_dir / "config")
            client = TestClient(app)
            try:
                client.post("/v1/route", json={
                    "message": "用户A的消息",
                    "user_id": "ou_user_a",
                    "stream": False,
                })
                client.post("/v1/route", json={
                    "message": "用户B的消息",
                    "user_id": "ou_user_b",
                    "stream": False,
                })
                import asyncio
                from agentmind.storage.memory import search_memory
                # A 只能看到自己的
                results_a = asyncio.run(search_memory(user_id="ou_user_a"))
                results_b = asyncio.run(search_memory(user_id="ou_user_b"))
                assert len(results_a) >= 1
                assert len(results_b) >= 1
                # A 的结果不包含 B 的内容
                a_contents = [r.get("content", "") for r in results_a]
                assert not any("用户B" in c for c in a_contents)
            finally:
                mp.undo()
