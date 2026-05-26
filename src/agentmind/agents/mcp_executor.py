"""MCP (Model Context Protocol) 执行器 — JSON-RPC 2.0 over stdio"""

import asyncio
import json
import shlex
import time
from datetime import datetime, timezone
from typing import AsyncIterator

from agentmind.agents.base import BaseAgentExecutor, StreamEvent, StreamEventType, TaskResult

MCP_INIT_REQUEST = json.dumps({
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "AgentMind", "version": "1.0"}},
})


def _build_jsonrpc(method: str, params: dict, request_id: int) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})


class MCPExecutor(BaseAgentExecutor):
    """MCP 类型 Agent 执行器：通过 JSON-RPC 2.0 over stdio 连接 MCP 工具服务器

    config 字段：
        command: str            MCP server 启动命令，如 "python mcp_server.py"
        command_args: list[str] 参数列表（优先于 command）
        tool_name: str          要调用的工具名称
        tool_args: dict         工具参数模板（支持 {instruction} 占位符）
        health_check: str       健康检查命令
    """

    def _build_cmd_args(self) -> list[str]:
        cmd_args = self.capability.config.get("command_args")
        if cmd_args and isinstance(cmd_args, list):
            return cmd_args
        command = self.capability.config.get("command", "")
        if not command:
            return []
        try:
            return shlex.split(command)
        except ValueError:
            return command.split()

    async def execute(self, instruction: str, context: dict = None) -> TaskResult:
        start_time = time.time()
        cmd_args = self._build_cmd_args()
        if not cmd_args:
            return TaskResult(success=False, output="", error="未配置 MCP server command")

        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # 1. initialize
            process.stdin.write((MCP_INIT_REQUEST + "\n").encode())
            await process.stdin.drain()
            try:
                init_line = await asyncio.wait_for(process.stdout.readline(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return TaskResult(success=False, output="", error="MCP initialize 超时")
            if not init_line:
                process.kill()
                await process.wait()
                return TaskResult(success=False, output="", error="MCP initialize 无响应")

            # 2. 构造 tools/call 请求
            tool_name = self.capability.config.get("tool_name", "")
            if not tool_name:
                process.kill()
                await process.wait()
                return TaskResult(success=False, output="", error="未配置 tool_name")

            tool_args = self.capability.config.get("tool_args", {})
            params = dict(tool_args)
            for k, v in params.items():
                if isinstance(v, str):
                    params[k] = v.replace("{instruction}", instruction)

            req = _build_jsonrpc("tools/call", {"name": tool_name, "arguments": params}, 2)
            process.stdin.write((req + "\n").encode())
            await process.stdin.drain()

            # 3. 读响应
            try:
                resp_line = await asyncio.wait_for(process.stdout.readline(), timeout=self.capability.timeout)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return TaskResult(
                    success=False, output="", error="MCP tools/call 超时",
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )
            process.stdin.close()
            await process.wait()

            execution_time = int((time.time() - start_time) * 1000)

            if not resp_line:
                return TaskResult(success=False, output="", error="MCP tools/call 无响应", execution_time_ms=execution_time)

            resp = json.loads(resp_line.decode())
            if resp.get("error"):
                return TaskResult(
                    success=False, output="",
                    error=str(resp["error"].get("message", resp["error"])),
                    execution_time_ms=execution_time,
                )
            result = resp.get("result", {})
            content = result.get("content", [])
            if isinstance(content, list):
                output = "\n".join(
                    c.get("text", str(c)) if isinstance(c, dict) else str(c)
                    for c in content
                )
            else:
                output = str(content)
            return TaskResult(success=True, output=output, execution_time_ms=execution_time)

        except asyncio.TimeoutError:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            return TaskResult(
                success=False, output="", error="MCP 执行超时",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as e:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            return TaskResult(
                success=False, output="", error=str(e),
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    async def execute_stream(self, instruction: str, context: dict = None) -> AsyncIterator[StreamEvent]:
        result = await self.execute(instruction, context)
        if result.success:
            yield StreamEvent(type=StreamEventType.CONTENT, text=result.output)
        else:
            yield StreamEvent(type=StreamEventType.ERROR, text=result.error)

    async def health_check(self) -> bool:
        cmd_args = self._build_cmd_args()
        if not cmd_args:
            self.is_healthy = False
            self.last_health_check = datetime.now(timezone.utc).isoformat()
            return False
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            process.stdin.write((MCP_INIT_REQUEST + "\n").encode())
            await process.stdin.drain()
            line = await asyncio.wait_for(process.stdout.readline(), timeout=5)
            process.stdin.close()
            await process.wait()
            if line:
                try:
                    resp = json.loads(line.decode())
                    self.is_healthy = resp.get("jsonrpc") == "2.0" and "result" in resp
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self.is_healthy = False
            else:
                self.is_healthy = False
        except asyncio.TimeoutError:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            self.is_healthy = False
        except Exception:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            self.is_healthy = False
        self.last_health_check = datetime.now(timezone.utc).isoformat()
        return self.is_healthy
