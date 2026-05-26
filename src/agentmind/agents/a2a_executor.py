"""A2A (Agent-to-Agent) 执行器 — HTTP POST 调用远程 Agent"""

import time
from datetime import datetime, timezone
from typing import AsyncIterator

import httpx

from agentmind.agents.base import BaseAgentExecutor, StreamEvent, StreamEventType, TaskResult


class A2AExecutor(BaseAgentExecutor):
    """A2A 类型 Agent 执行器：通过 HTTP POST 调用远程 Agent 端点

    config 字段：
        endpoint: str        远程 Agent 端点的完整 URL
        headers: dict        请求头（如 {"X-API-Key": "..."}）
        health_endpoint: str 健康检查端点（可选，默认 GET {endpoint}/health）
    """

    async def execute(self, instruction: str, context: dict = None) -> TaskResult:
        start_time = time.time()
        endpoint = self.capability.config.get("endpoint", "")
        if not endpoint:
            return TaskResult(success=False, output="", error="未配置 A2A endpoint")

        headers = self.capability.config.get("headers", {})
        payload = {"instruction": instruction}
        if context:
            payload["context"] = context

        try:
            async with httpx.AsyncClient(timeout=self.capability.timeout) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)
                execution_time = int((time.time() - start_time) * 1000)

                if resp.status_code == 200:
                    _MAX_BYTES = 1 * 1024 * 1024  # 1MB
                    if len(resp.content) > _MAX_BYTES:
                        return TaskResult(
                            success=False, output="",
                            error=f"A2A 响应超过1MB限制（{len(resp.content)} bytes），已拒绝",
                            execution_time_ms=execution_time,
                        )
                    data = resp.json()
                    if data.get("error"):
                        return TaskResult(success=False, output="", error=data["error"], execution_time_ms=execution_time)
                    return TaskResult(success=True, output=data.get("output", resp.text), execution_time_ms=execution_time)
                else:
                    return TaskResult(
                        success=False, output="",
                        error=f"A2A HTTP {resp.status_code}: {resp.text[:200]}",
                        execution_time_ms=execution_time,
                    )
        except Exception as e:
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
        endpoint = self.capability.config.get("endpoint", "")
        if not endpoint:
            self.is_healthy = False
            self.last_health_check = datetime.now(timezone.utc).isoformat()
            return False

        health_url = self.capability.config.get("health_endpoint", "")
        if not health_url:
            health_url = endpoint.rstrip("/") + "/health"

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(health_url)
                self.is_healthy = resp.status_code == 200
        except Exception:
            self.is_healthy = False
        self.last_health_check = datetime.now(timezone.utc).isoformat()
        return self.is_healthy
