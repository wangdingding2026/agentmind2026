import os
import time
from datetime import datetime, timezone
from typing import AsyncIterator

import httpx

from agentmind.agents.base import BaseAgentExecutor, StreamEvent, StreamEventType, TaskResult


class APIExecutor(BaseAgentExecutor):
    """API 类型 Agent 执行器：通过 HTTP REST 请求调用远程服务

    config 字段：
        endpoint: str              请求地址
        method: str                HTTP 方法，默认 POST
        headers: dict              请求头（支持 {api_key} 占位符）
        body_template: dict        请求体模板（支持 {instruction} 占位符）
        response_path: str         响应提取路径，如 "choices.0.message.content"
        api_key: str               API Key（可选，也可从环境变量 {env:VAR_NAME} 读取）
    """

    def _get_api_key(self) -> str:
        """读取 API Key：优先从 config 读取，其次从环境变量"""
        cfg = self.capability.config
        api_key = cfg.get("api_key", "")

        # 支持环境变量引用，格式：{env:VAR_NAME}
        if api_key.startswith("{env:") and api_key.endswith("}"):
            env_var = api_key[5:-1]
            api_key = os.environ.get(env_var, "")

        return api_key

    def _resolve_placeholders(self, obj, api_key: str = "", instruction: str = ""):
        """递归替换占位符"""
        if isinstance(obj, str):
            return obj.replace("{api_key}", api_key).replace("{instruction}", instruction)
        if isinstance(obj, dict):
            return {k: self._resolve_placeholders(v, api_key, instruction) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._resolve_placeholders(v, api_key, instruction) for v in obj]
        return obj

    def _extract_path(self, data, path: str):
        """按点分路径从 dict 中提取值"""
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

    async def execute(self, instruction: str, context: dict = None) -> TaskResult:
        start_time = time.time()
        cfg = self.capability.config
        endpoint = cfg.get("endpoint", "")
        if not endpoint:
            return TaskResult(success=False, output="", error="未配置 endpoint")

        method = cfg.get("method", "POST").upper()
        api_key = self._get_api_key()
        headers = self._resolve_placeholders(cfg.get("headers", {}), api_key=api_key, instruction=instruction)
        body = self._resolve_placeholders(cfg.get("body_template", {}), api_key=api_key, instruction=instruction)

        try:
            async with httpx.AsyncClient(timeout=self.capability.timeout) as client:
                response = await client.request(method, endpoint, json=body, headers=headers)
                execution_time = int((time.time() - start_time) * 1000)

                if response.status_code == 200:
                    _MAX_BYTES = 1 * 1024 * 1024  # 1MB
                    if len(response.content) > _MAX_BYTES:
                        return TaskResult(
                            success=False,
                            output="",
                            error=f"API 响应超过1MB限制（{len(response.content)} bytes），已拒绝",
                            execution_time_ms=execution_time,
                        )
                    response_path = cfg.get("response_path", "")
                    if response_path:
                        content = self._extract_path(response.json(), response_path)
                        output = str(content) if content is not None else response.text
                    else:
                        output = response.text
                    return TaskResult(success=True, output=output, execution_time_ms=execution_time)
                else:
                    return TaskResult(
                        success=False,
                        output="",
                        error=f"HTTP {response.status_code}: {response.text[:200]}",
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
        hc_config = self.capability.config.get("health_check_config", {})
        endpoint = hc_config.get("url", self.capability.config.get("endpoint", ""))
        if not endpoint:
            self.is_healthy = False
            self.last_health_check = datetime.now(timezone.utc).isoformat()
            return False

        method = hc_config.get("method", "GET")
        expected_status = hc_config.get("expected_status", 200)
        hc_headers = hc_config.get("headers", {})
        hc_body = hc_config.get("body")

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.request(
                    method, endpoint,
                    headers=hc_headers or None,
                    json=hc_body if hc_body else None,
                )
                self.is_healthy = response.status_code == expected_status
        except Exception:
            self.is_healthy = False
        self.last_health_check = datetime.now(timezone.utc).isoformat()
        return self.is_healthy
