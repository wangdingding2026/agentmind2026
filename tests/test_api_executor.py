import os
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from agentmind.agents.base import AgentCapability
from agentmind.agents.api_executor import APIExecutor


def make_api_executor(endpoint="http://localhost:11434/api/chat", **config_extra):
    cap = AgentCapability(
        id="test_api", name="Test API", type="api",
        tags=["test"], enabled=True, timeout=10,
        config={"endpoint": endpoint, "method": "POST", **config_extra},
    )
    return APIExecutor(cap)


class TestAPIExecute:
    @pytest.mark.asyncio
    async def test_execute_success(self):
        ex = make_api_executor(response_path="data.content")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"content": "hello"}}
        mock_response.text = '{"data":{"content":"hello"}}'

        with patch("agentmind.agents.api_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await ex.execute("test")
            assert result.success
            assert result.output == "hello"

    @pytest.mark.asyncio
    async def test_execute_no_endpoint(self):
        cap = AgentCapability(
            id="test", name="Test", type="api",
            tags=[], enabled=True, timeout=5, config={},
        )
        ex = APIExecutor(cap)
        result = await ex.execute("test")
        assert not result.success
        assert "未配置" in result.error

    @pytest.mark.asyncio
    async def test_execute_http_error(self):
        ex = make_api_executor()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Error"

        with patch("agentmind.agents.api_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await ex.execute("test")
            assert not result.success
            assert "500" in result.error


class TestAPIHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_200(self):
        ex = make_api_executor()
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("agentmind.agents.api_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await ex.health_check()
            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_401_not_healthy(self):
        ex = make_api_executor()
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("agentmind.agents.api_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await ex.health_check()
            assert result is False

    @pytest.mark.asyncio
    async def test_health_check_custom_config(self):
        ex = make_api_executor(health_check_config={
            "url": "http://localhost:11434/health",
            "method": "GET",
            "expected_status": 200,
        })
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("agentmind.agents.api_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await ex.health_check()
            assert result is True
            mock_client.request.assert_called_once_with(
                "GET", "http://localhost:11434/health", headers=None, json=None,
            )


class TestResolvePlaceholders:
    def test_simple_replacement(self):
        ex = make_api_executor()
        result = ex._resolve_placeholders("key: {api_key}", api_key="sk-123")
        assert result == "key: sk-123"

    def test_nested_dict(self):
        ex = make_api_executor()
        result = ex._resolve_placeholders(
            {"body": {"msg": "{instruction}"}}, instruction="hello"
        )
        assert result == {"body": {"msg": "hello"}}

    def test_env_var(self):
        os.environ["TEST_AGENTMIND_KEY"] = "env-key-123"
        try:
            cap = AgentCapability(
                id="test", name="Test", type="api",
                tags=[], enabled=True, timeout=5,
                config={"endpoint": "http://x", "api_key": "{env:TEST_AGENTMIND_KEY}"},
            )
            ex = APIExecutor(cap)
            assert ex._get_api_key() == "env-key-123"
        finally:
            del os.environ["TEST_AGENTMIND_KEY"]


class TestExtractPath:
    def test_normal_path(self):
        ex = make_api_executor()
        data = {"a": {"b": "value"}}
        assert ex._extract_path(data, "a.b") == "value"

    def test_array_index(self):
        ex = make_api_executor()
        data = {"items": ["first", "second"]}
        assert ex._extract_path(data, "items.0") == "first"

    def test_missing_path(self):
        ex = make_api_executor()
        data = {"a": 1}
        assert ex._extract_path(data, "x.y.z") is None


class TestAPIExecuteTruncation:
    """APIExecutor 输出上限测试"""

    @pytest.mark.asyncio
    async def test_large_response_truncated(self, monkeypatch):
        """超过 1MB 的响应应被拒绝"""
        import httpx
        from agentmind.agents.base import AgentCapability

        cap = AgentCapability(
            id="test_api", name="Test", type="api", tags=[],
            timeout=5, config={"endpoint": "http://localhost/api", "method": "POST"},
        )
        ex = __import__("agentmind.agents.api_executor", fromlist=["APIExecutor"]).APIExecutor(cap)

        mock_response = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"x" * (2 * 1024 * 1024)  # 2MB
        mock_response.text = "x" * (2 * 1024 * 1024)
        mock_response.json.return_value = {}

        mock_client = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock()
        mock_client.request = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(return_value=False)

        mock_cls = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock(return_value=mock_client)
        monkeypatch.setattr(httpx, "AsyncClient", mock_cls)

        result = await ex.execute("test")
        assert result.success is False
        assert "1MB" in result.error
