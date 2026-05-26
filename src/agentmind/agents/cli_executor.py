import asyncio
import json
import shlex
import time
from datetime import datetime, timezone
from typing import AsyncIterator

from agentmind.agents.base import BaseAgentExecutor, StreamEvent, StreamEventType, TaskResult

_MAX_CONCURRENT_PROCESSES = 5
_MAX_OUTPUT_BYTES = 1024 * 1024  # 1MB


def _extract_json_path(data, path: str):
    """按点分路径从 dict/list 中提取值，如 payloads.0.text"""
    keys = path.split(".")
    result = data
    for key in keys:
        if isinstance(result, dict) and key in result:
            result = result[key]
        elif isinstance(result, list) and key.isdigit():
            result = result[int(key)]
        else:
            return None
    return result
_global_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_PROCESSES)


class CLIExecutor(BaseAgentExecutor):
    """CLI 类型 Agent 执行器：通过 subprocess 调用命令行工具

    config 字段：
        command: str               命令模板，如 "claude -p '{instruction}'"，用 shlex 解析
        command_args: list[str]    直接指定参数列表（优先于 command，避免解析问题）
        health_check: str          健康检查命令，如 "claude --version"
        health_check_args: list    健康检查参数列表（优先于 health_check）
    """

    def _build_cmd_args(self, instruction: str) -> list[str]:
        """从配置构建参数列表，优先用 command_args，否则用 shlex 解析 command"""
        # 优先使用直接的参数列表
        cmd_args = self.capability.config.get("command_args")
        if cmd_args and isinstance(cmd_args, list):
            return [instruction if a in ("{instruction}", "'{instruction}'") else a for a in cmd_args]

        # 用 shlex 解析命令字符串，正确处理引号和空格
        command = self.capability.config.get("command", "")
        if not command:
            return []
        try:
            parts = shlex.split(command)
        except ValueError:
            # shlex 解析失败（如不匹配的引号），回退到简单 split
            parts = command.split()
        args = []
        for part in parts:
            if part == "'{instruction}'" or part == "{instruction}":
                args.append(instruction)
            else:
                args.append(part)
        return args

    def _get_health_check_args(self) -> list[str]:
        """构建健康检查参数列表"""
        # 优先使用直接的参数列表
        hc_args = self.capability.config.get("health_check_args")
        if hc_args and isinstance(hc_args, list):
            return hc_args

        health_cmd = self.capability.config.get("health_check", "")
        if health_cmd:
            try:
                return shlex.split(health_cmd)
            except ValueError:
                return health_cmd.split()
        # 兜底：取 command 的第一个词 + --version
        command = self.capability.config.get("command", "")
        if command:
            try:
                base_cmd = shlex.split(command)[0]
            except ValueError:
                base_cmd = command.split()[0]
            if base_cmd:
                return [base_cmd, "--version"]
        return []

    async def execute_stream(self, instruction: str, context: dict = None) -> AsyncIterator[StreamEvent]:
        cmd_args = self._build_cmd_args(instruction)
        if not cmd_args:
            yield StreamEvent(type=StreamEventType.ERROR, text="未配置 command")
            return

        async with _global_semaphore:
            process = None
            stderr_task = None
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd_args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                stderr_chunks: list[str] = []
                output_bytes = 0

                async def _drain_stderr():
                    while True:
                        line = await process.stderr.readline()
                        if not line:
                            break
                        stderr_chunks.append(line.decode("utf-8", errors="replace"))

                stderr_task = asyncio.create_task(_drain_stderr())

                start_time = time.time()
                last_output_time = start_time
                TIMEOUT = self.capability.timeout
                total_deadline = start_time + TIMEOUT * 2  # 总执行时长上限
                timed_out = False
                output_truncated = False

                while True:
                    # 检查总 deadline
                    if time.time() > total_deadline:
                        yield StreamEvent(type=StreamEventType.ERROR, text=f"Agent 总执行时间超过{TIMEOUT * 2}秒，终止执行")
                        timed_out = True
                        break

                    idle_elapsed = time.time() - last_output_time
                    if idle_elapsed >= TIMEOUT:
                        yield StreamEvent(type=StreamEventType.ERROR, text=f"Agent {TIMEOUT}秒内无输出，终止执行")
                        timed_out = True
                        break
                    # 等待下一行：最多等 idle 剩余时间，但不超过总 deadline
                    wait_timeout = min(TIMEOUT - idle_elapsed, total_deadline - time.time())
                    wait_timeout = max(wait_timeout, 1)  # 至少 1 秒，避免忙轮询
                    try:
                        line = await asyncio.wait_for(process.stdout.readline(), timeout=wait_timeout)
                    except asyncio.TimeoutError:
                        # wait_for 超时意味着在允许窗口内无新输出，回到循环顶部检查 deadline
                        continue

                    if not line:
                        break
                    last_output_time = time.time()

                    decoded = line.decode("utf-8", errors="replace")
                    output_bytes += len(decoded.encode("utf-8"))
                    if output_bytes > _MAX_OUTPUT_BYTES:
                        if not output_truncated:
                            yield StreamEvent(type=StreamEventType.ERROR, text="输出超过1MB限制，已截断")
                            output_truncated = True
                        break

                    yield StreamEvent(type=StreamEventType.CONTENT, text=decoded)

                if not timed_out and not output_truncated:
                    await process.wait()
                    await stderr_task
                else:
                    process.kill()
                    await process.wait()
                    stderr_task.cancel()
                    try:
                        await stderr_task
                    except asyncio.CancelledError:
                        pass
                    # 超时时也输出 stderr 便于排查
                    if stderr_chunks:
                        stderr_text = "".join(stderr_chunks)
                        yield StreamEvent(type=StreamEventType.ERROR, text=f"Agent stderr: {stderr_text[:200]}")

                if process.returncode != 0 and not timed_out and not output_truncated:
                    error_msg = "".join(stderr_chunks)
                    yield StreamEvent(type=StreamEventType.ERROR, text=f"Agent 退出码 {process.returncode}，错误信息：{error_msg[:200]}")

            except asyncio.CancelledError:
                if process and process.returncode is None:
                    process.kill()
                    await process.wait()
                if stderr_task and not stderr_task.done():
                    stderr_task.cancel()
                    try:
                        await stderr_task
                    except asyncio.CancelledError:
                        pass
                raise
            except Exception as e:
                if process and process.returncode is None:
                    process.kill()
                    await process.wait()
                if stderr_task and not stderr_task.done():
                    stderr_task.cancel()
                yield StreamEvent(type=StreamEventType.ERROR, text=str(e))

    async def execute(self, instruction: str, context: dict = None) -> TaskResult:
        start_time = time.time()
        process = None
        try:
            cmd_args = self._build_cmd_args(instruction)
            if not cmd_args:
                return TaskResult(success=False, output="", error="未配置 command")

            async with _global_semaphore:
                process = await asyncio.create_subprocess_exec(
                    *cmd_args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                # 增量读取，避免内存峰值
                stdout_chunks = []
                stderr_chunks = []
                output_bytes = 0
                deadline = start_time + self.capability.timeout * 2

                async def _drain_stderr():
                    while True:
                        line = await process.stderr.readline()
                        if not line:
                            break
                        if sum(len(c.encode("utf-8")) for c in stderr_chunks) < _MAX_OUTPUT_BYTES:
                            stderr_chunks.append(line.decode("utf-8", errors="replace"))

                stderr_task = asyncio.create_task(_drain_stderr())

                try:
                    while True:
                        if time.time() > deadline:
                            process.kill()
                            await process.wait()
                            stderr_task.cancel()
                            try:
                                await stderr_task
                            except asyncio.CancelledError:
                                pass
                            return TaskResult(
                                success=False, output="",
                                error=f"执行超时（总时长超过{self.capability.timeout * 2}秒）",
                                execution_time_ms=int((time.time() - start_time) * 1000),
                            )
                        try:
                            line = await asyncio.wait_for(
                                process.stdout.readline(),
                                timeout=max(5, deadline - time.time()),
                            )
                        except asyncio.TimeoutError:
                            process.kill()
                            await process.wait()
                            stderr_task.cancel()
                            try:
                                await stderr_task
                            except asyncio.CancelledError:
                                pass
                            return TaskResult(
                                success=False, output="",
                                error=f"执行超时（{self.capability.timeout}秒内无输出）",
                                execution_time_ms=int((time.time() - start_time) * 1000),
                            )

                        if not line:
                            break
                        decoded = line.decode("utf-8", errors="replace")
                        output_bytes += len(decoded.encode("utf-8"))
                        if output_bytes > _MAX_OUTPUT_BYTES:
                            process.kill()
                            await process.wait()
                            stderr_task.cancel()
                            try:
                                await stderr_task
                            except asyncio.CancelledError:
                                pass
                            execution_time = int((time.time() - start_time) * 1000)
                            return TaskResult(
                                success=False,
                                output="",
                                error="输出超过1MB限制，已终止执行",
                                execution_time_ms=execution_time,
                            )
                        stdout_chunks.append(decoded)

                    await process.wait()
                    try:
                        await stderr_task
                    except asyncio.CancelledError:
                        pass

                except Exception:
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
                    if stderr_task and not stderr_task.done():
                        stderr_task.cancel()
                        try:
                            await stderr_task
                        except asyncio.CancelledError:
                            pass
                    raise

            execution_time = int((time.time() - start_time) * 1000)
            output = "".join(stdout_chunks)

            # 如果配置了 response_path，尝试从 JSON 输出中提取
            response_path = self.capability.config.get("response_path", "")
            if response_path and output.strip().startswith("{"):
                try:
                    parsed = json.loads(output)
                    extracted = _extract_json_path(parsed, response_path)
                    if extracted is not None:
                        output = str(extracted)
                except (json.JSONDecodeError, Exception):
                    pass

            if process.returncode == 0:
                return TaskResult(success=True, output=output, execution_time_ms=execution_time)
            else:
                return TaskResult(
                    success=False,
                    output="",
                    error="".join(stderr_chunks),
                    execution_time_ms=execution_time,
                )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return TaskResult(
                success=False,
                output="",
                error=f"执行超时（{self.capability.timeout}秒）",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as e:
            return TaskResult(
                success=False,
                output="",
                error=str(e),
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    async def health_check(self) -> bool:
        cmd_args = self._get_health_check_args()
        if not cmd_args:
            self.is_healthy = False
            self.last_health_check = datetime.now(timezone.utc).isoformat()
            return False
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(process.communicate(), timeout=5)
            self.is_healthy = process.returncode == 0
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
