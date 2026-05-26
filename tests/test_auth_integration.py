"""集成测试：验证真实 create_app() 中的认证中间件行为"""
import tempfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient


@pytest.fixture
def auth_test_client():
    """创建使用真实 create_app() 的 TestClient，含完整认证中间件"""
    mp = pytest.MonkeyPatch()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        data_dir = tmp_dir / "data"
        config_dir = tmp_dir / "config"
        logs_dir = tmp_dir / "logs"
        (data_dir / "results").mkdir(parents=True, exist_ok=True)
        config_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)

        # patch 路径
        mp.setattr("agentmind.storage.db.DATA_DIR", data_dir)
        mp.setattr("agentmind.storage.db.DATA_HOME", tmp_dir)
        mp.setattr("agentmind.storage.db.CONFIG_DIR", config_dir)
        mp.setattr("agentmind.storage.db.LOGS_DIR", logs_dir)
        mp.setattr("agentmind.main.DATA_HOME", tmp_dir)

        # 写入测试用配置文件
        agents_config = {
            "agents": [
                {
                    "id": "test_cli", "name": "Test CLI", "type": "cli",
                    "tags": ["code"], "enabled": True, "timeout": 5,
                    "config": {"command": "echo done", "health_check": "echo ok"},
                }
            ]
        }
        routes_config = {
            "rules": [
                {"name": "code_kw", "type": "keyword", "patterns": ["写一个", "代码"], "target_tags": ["code"], "priority": 10, "tags": ["code"]},
            ]
        }
        (config_dir / "agents.yaml").write_text(yaml.dump(agents_config, allow_unicode=True), encoding="utf-8")
        (config_dir / "routes.yaml").write_text(yaml.dump(routes_config, allow_unicode=True), encoding="utf-8")

        # 初始化数据库
        from agentmind.storage.db import initialize_data_directory
        initialize_data_directory()

        # 创建 app（端口 0 仅为占位）
        from agentmind.main import create_app
        app = create_app(0)
        client = TestClient(app)

        # 标记已注册 executor 为健康，让路由可用
        for ex in app.state.agent_registry.executors.values():
            ex.is_healthy = True

        yield client, app.state.auth_token

    mp.undo()


class TestAuthMiddleware:
    """认证中间件集成测试"""

    def test_no_token_returns_401(self, auth_test_client):
        """无 token 的 POST 请求返回 401"""
        client, _ = auth_test_client
        resp = client.post("/v1/agents/scan")
        assert resp.status_code == 401
        assert "Unauthorized" in resp.text

    def test_wrong_token_returns_401(self, auth_test_client):
        """错误 token 返回 401"""
        client, _ = auth_test_client
        resp = client.post(
            "/v1/agents/scan",
            headers={"Authorization": "Bearer wrong-token-value"},
        )
        assert resp.status_code == 401

    def test_correct_token_returns_ok(self, auth_test_client):
        """正确 token 返回成功（scan 可能 200 或业务错误，但不是 401）"""
        client, token = auth_test_client
        resp = client.post(
            "/v1/agents/scan",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code != 401

    def test_local_origin_without_token_returns_401(self, auth_test_client):
        """本地 Origin 但不带 token 也必须返回 401（核心修复验证）"""
        client, _ = auth_test_client
        resp = client.post(
            "/v1/agents/scan",
            headers={"Origin": "http://127.0.0.1:8765"},
        )
        assert resp.status_code == 401

    def test_nonlocal_origin_returns_403(self, auth_test_client):
        """非本地 Origin 即使带正确 token 也返回 403（CSRF 防护）"""
        client, token = auth_test_client
        resp = client.post(
            "/v1/agents/scan",
            headers={
                "Authorization": f"Bearer {token}",
                "Origin": "http://evil.example.com",
            },
        )
        assert resp.status_code == 403

    def test_cookie_token_works(self, auth_test_client):
        """通过 cookie 携带 token 可以成功"""
        client, token = auth_test_client
        resp = client.post(
            "/v1/agents/scan",
            cookies={"agentmind_token": token},
        )
        assert resp.status_code != 401

    def test_route_endpoint_with_token(self, auth_test_client):
        """带 token 调用 /v1/route 非流式"""
        client, token = auth_test_client
        resp = client.post(
            "/v1/route",
            json={"message": "hello", "stream": False},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code in (200, 503)  # 503 = 无健康 agent，但认证通过

    def test_health_check_endpoint_with_token(self, auth_test_client):
        """带 token 调用 health-check"""
        client, token = auth_test_client
        resp = client.post(
            "/v1/agents/test_cli/health-check",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_health_check_without_token_returns_401(self, auth_test_client):
        """无 token 调用 health-check 返回 401"""
        client, _ = auth_test_client
        resp = client.post("/v1/agents/test_cli/health-check")
        assert resp.status_code == 401

    def test_panel_get_without_token_returns_401(self, auth_test_client):
        """GET /panel/api/* 无 token 返回 401（面板 API 统一要求认证）"""
        client, _ = auth_test_client
        resp = client.get("/panel/api/agents")
        assert resp.status_code == 401

    def test_panel_get_tasks_without_token_returns_401(self, auth_test_client):
        """GET /panel/api/tasks 无 token 返回 401"""
        client, _ = auth_test_client
        resp = client.get("/panel/api/tasks")
        assert resp.status_code == 401

    def test_panel_get_tasks_with_cookie_returns_200(self, auth_test_client):
        """GET /panel/api/tasks 带 cookie token 返回 200"""
        client, token = auth_test_client
        resp = client.get("/panel/api/tasks", cookies={"agentmind_token": token})
        assert resp.status_code == 200

    def test_panel_get_agents_with_cookie_returns_200(self, auth_test_client):
        """GET /panel/api/agents 带 cookie token 返回 200"""
        client, token = auth_test_client
        resp = client.get("/panel/api/agents", cookies={"agentmind_token": token})
        assert resp.status_code == 200

    def test_panel_page_sets_cookie(self, auth_test_client):
        """访问面板页面设置认证 cookie"""
        client, token = auth_test_client
        resp = client.get("/panel/")
        assert resp.status_code == 200
        assert "agentmind_token" in resp.cookies
        assert resp.cookies["agentmind_token"] == token

    def test_panel_cookie_max_age_is_7_days(self, auth_test_client):
        """面板 cookie Max-Age 应为 7 天"""
        client, _ = auth_test_client
        resp = client.get("/panel/")
        set_cookie = resp.headers.get("set-cookie", "")
        assert "Max-Age=604800" in set_cookie  # 86400 * 7

    def test_token_not_in_panel_html(self, auth_test_client):
        """面板 HTML 中不包含 token 原文"""
        client, token = auth_test_client
        resp = client.get("/panel/")
        assert token not in resp.text

    def test_panel_restart_requires_token(self, auth_test_client):
        """面板 restart API 需要认证"""
        client, _ = auth_test_client
        resp = client.post("/panel/api/agents/test_cli/restart")
        assert resp.status_code == 401


class TestMaskConfig:
    """配置脱敏测试"""

    def test_mask_list_of_dicts(self):
        """headers 列表中的敏感字段应被脱敏"""
        from agentmind.panel.server import _mask_config

        config = {
            "endpoint": "http://api.example.com",
            "headers": [
                {"Authorization": "Bearer secret123"},
                {"Content-Type": "application/json"},
            ],
            "body_template": {"model": "llama3"},
        }
        masked = _mask_config(config)
        assert masked["endpoint"] == "http://api.example.com"
        assert masked["headers"][0]["Authorization"] == "****"
        assert masked["headers"][1]["Content-Type"] == "application/json"
        assert masked["body_template"]["model"] == "llama3"

    def test_mask_nested_api_key(self):
        """嵌套 dict 中的 api_key 应被脱敏"""
        from agentmind.panel.server import _mask_config

        config = {
            "connection": {
                "auth": {
                    "api_key": "sk-1234567890abcdef",
                    "timeout": 30,
                }
            }
        }
        masked = _mask_config(config)
        assert masked["connection"]["auth"]["api_key"] == "****"
        assert masked["connection"]["auth"]["timeout"] == 30

    def test_mask_top_level_token(self):
        """顶层 token 字段应被脱敏"""
        from agentmind.panel.server import _mask_config

        config = {"token": "my-secret-token", "other": "visible"}
        masked = _mask_config(config)
        assert masked["token"] == "****"
        assert masked["other"] == "visible"


class TestEmptyToken:
    """P1：空 auth.token 绕过认证"""

    def test_empty_token_file_rejected(self, tmp_dir):
        """空 token 文件应触发重新生成，认证中间件应拒绝空 token"""
        import pytest
        from agentmind.storage.db import DATA_HOME as orig_home

        mp = pytest.MonkeyPatch()
        mp.setattr("agentmind.main.DATA_HOME", tmp_dir)
        mp.setattr("agentmind.storage.db.DATA_HOME", tmp_dir)
        mp.setattr("agentmind.storage.db.DATA_DIR", tmp_dir / "data")
        mp.setattr("agentmind.storage.db.CONFIG_DIR", tmp_dir / "config")
        mp.setattr("agentmind.storage.db.LOGS_DIR", tmp_dir / "logs")
        (tmp_dir / "data" / "results").mkdir(parents=True, exist_ok=True)
        (tmp_dir / "config").mkdir(parents=True, exist_ok=True)

        # 初始化 DB
        from agentmind.storage.db import initialize_data_directory
        initialize_data_directory()

        # 写入空的 auth.token
        (tmp_dir / "config" / "auth.token").write_text("   \n", encoding="utf-8")

        # 写 agents.yaml 和 routes.yaml
        import yaml
        (tmp_dir / "config" / "agents.yaml").write_text(yaml.dump({"agents": []}), encoding="utf-8")
        (tmp_dir / "config" / "routes.yaml").write_text(yaml.dump({"rules": []}), encoding="utf-8")

        from agentmind.main import create_app
        app = create_app(0)
        token = app.state.auth_token

        # token 应被重新生成（长度 >= 32）
        assert len(token) >= 32
        # 空 token 请求应返回 401
        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.post("/v1/agents/scan")
        assert resp.status_code == 401

        mp.undo()
