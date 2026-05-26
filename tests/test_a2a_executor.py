"""A2A Executor 测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock


def make_a2a_executor(**config):
    from agentmind.agents.base import AgentCapability
    from agentmind.agents.a2a_executor import A2AExecutor

    cfg = {"endpoint": "http://localhost:9999/api/agent", **config}
    return A2AExecutor(AgentCapability(id="a2a_test", name="A2A Test", type="a2a", tags=[], timeout=5, config=cfg))


class TestA2AExecute:
    @pytest.mark.asyncio
    async def test_no_endpoint(self):
        ex = make_a2a_executor(endpoint="")
        result = await ex.execute("test")
        assert result.success is False
        assert "未配置" in result.error

    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"output": "A2A response here"}
        mock_resp.text = "A2A response here"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", MagicMock(return_value=mock_client))

        ex = make_a2a_executor()
        result = await ex.execute("hello")
        assert result.success is True
        assert result.output == "A2A response here"

    @pytest.mark.asyncio
    async def test_error_response(self, monkeypatch):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"error": "Internal server error"}
        mock_resp.text = ""

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", MagicMock(return_value=mock_client))

        ex = make_a2a_executor()
        result = await ex.execute("hello")
        assert result.success is False
        assert "Internal server error" in result.error


class TestA2AHealthCheck:
    @pytest.mark.asyncio
    async def test_no_endpoint(self):
        ex = make_a2a_executor(endpoint="")
        result = await ex.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", MagicMock(return_value=mock_client))

        ex = make_a2a_executor()
        result = await ex.health_check()
        assert result is True


class TestA2AStream:
    @pytest.mark.asyncio
    async def test_stream_no_endpoint(self):
        ex = make_a2a_executor(endpoint="")
        events = []
        async for event in ex.execute_stream("test"):
            events.append(event)
        assert len(events) == 1
        assert events[0].type.value == "error"
