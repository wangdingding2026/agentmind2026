import asyncio

import pytest

from agentmind.agents.base import AgentCapability
from agentmind.agents.cli_executor import CLIExecutor


def make_cli_executor(command="echo '{instruction}'", timeout=5, **config_extra):
    cap = AgentCapability(
        id="test_cli", name="Test CLI", type="cli",
        tags=["test"], enabled=True, timeout=timeout,
        config={"command": command, "health_check": "echo ok", **config_extra},
    )
    return CLIExecutor(cap)


class TestBuildCmdArgs:
    def test_shlex_parse(self):
        ex = make_cli_executor(command="echo 'hello world'")
        args = ex._build_cmd_args("test")
        assert args == ["echo", "hello world"]

    def test_instruction_replacement(self):
        ex = make_cli_executor(command="echo '{instruction}'")
        args = ex._build_cmd_args("say hi")
        assert args == ["echo", "say hi"]

    def test_command_args_priority(self):
        ex = make_cli_executor(command_args=["echo", "{instruction}"])
        args = ex._build_cmd_args("hello")
        assert args == ["echo", "hello"]

    def test_empty_command(self):
        ex = make_cli_executor(command="")
        args = ex._build_cmd_args("hello")
        assert args == []


class TestCLIExecute:
    @pytest.mark.asyncio
    async def test_execute_success(self):
        ex = make_cli_executor(command="echo hello")
        result = await ex.execute("test")
        assert result.success
        assert "hello" in result.output

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        ex = make_cli_executor(command="sleep 10", timeout=1)
        result = await ex.execute("test")
        assert not result.success
        assert "超时" in result.error

    @pytest.mark.asyncio
    async def test_execute_no_command(self):
        ex = make_cli_executor(command="")
        result = await ex.execute("test")
        assert not result.success
        assert "未配置" in result.error


class TestCLIExecuteStream:
    @pytest.mark.asyncio
    async def test_stream_output(self):
        ex = make_cli_executor(command="echo hello")
        events = []
        async for event in ex.execute_stream("test"):
            events.append(event)
        contents = [e.text for e in events if e.type.value == "content"]
        assert any("hello" in c for c in contents)

    @pytest.mark.asyncio
    async def test_stream_no_command(self):
        ex = make_cli_executor(command="")
        events = []
        async for event in ex.execute_stream("test"):
            events.append(event)
        assert any(e.type.value == "error" for e in events)


class TestCLIHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_success(self):
        ex = make_cli_executor()
        result = await ex.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_no_command(self):
        cap = AgentCapability(
            id="test", name="Test", type="cli",
            tags=[], enabled=True, timeout=5, config={},
        )
        ex = CLIExecutor(cap)
        result = await ex.health_check()
        assert result is False
