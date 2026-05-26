"""MCP Executor 测试"""
import asyncio

import pytest


def make_mcp_executor(**config):
    from agentmind.agents.base import AgentCapability
    from agentmind.agents.mcp_executor import MCPExecutor

    cfg = {"command": "echo", "command_args": ["cat"], "tool_name": "test_tool", "tool_args": {"prompt": "{instruction}"}, **config}
    return MCPExecutor(AgentCapability(id="mcp_test", name="MCP Test", type="mcp", tags=[], timeout=5, config=cfg))


class TestMCPExecute:
    @pytest.mark.asyncio
    async def test_no_command(self):
        ex = make_mcp_executor(command="", command_args=None)
        result = await ex.execute("test")
        assert result.success is False
        assert "未配置" in result.error

    @pytest.mark.asyncio
    async def test_no_tool_name(self, monkeypatch):
        """模拟 MCP server 返回 initialize 响应但没有 tool_name 配置"""
        ex = make_mcp_executor(tool_name="")
        # 不实际启动子进程，直接验证 config 检查
        result = await ex.execute("test")
        assert result.success is False
        assert "tool_name" in result.error or "未配置" in result.error


class TestMCPHealthCheck:
    @pytest.mark.asyncio
    async def test_no_command(self):
        ex = make_mcp_executor(command="", command_args=None)
        result = await ex.health_check()
        assert result is False
        assert ex.last_health_check is not None


class TestMCPStream:
    @pytest.mark.asyncio
    async def test_stream_no_command(self):
        ex = make_mcp_executor(command="", command_args=None)
        events = []
        async for event in ex.execute_stream("test"):
            events.append(event)
        assert len(events) == 1
        assert events[0].type.value == "error"
