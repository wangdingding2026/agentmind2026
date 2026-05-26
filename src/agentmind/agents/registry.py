import asyncio
import logging
from pathlib import Path
from typing import Dict, Optional

import yaml

from agentmind.agents.base import AgentCapability, BaseAgentExecutor
from agentmind.agents.cli_executor import CLIExecutor
from agentmind.agents.api_executor import APIExecutor
from agentmind.agents.mcp_executor import MCPExecutor
from agentmind.agents.a2a_executor import A2AExecutor

logger = logging.getLogger("agentmind")

# type 字段 -> Executor 类的映射，新增连接协议只需在此扩展
EXECUTOR_MAP: Dict[str, type] = {
    "cli": CLIExecutor,
    "api": APIExecutor,
    "mcp": MCPExecutor,
    "a2a": A2AExecutor,
}


class AgentRegistry:
    def __init__(self, config_path: Path):
        self.executors: Dict[str, BaseAgentExecutor] = {}
        self._lock = asyncio.Lock()
        self.load_from_config(config_path)

    def _build_executors(self, config_path: Path) -> Dict[str, BaseAgentExecutor]:
        """从配置文件构建 executor 字典（纯函数，不修改 self）"""
        if not config_path.exists():
            return {}
        try:
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            logger.warning("agents.yaml 解析失败: %s，将使用空配置", e)
            return {}
        if not isinstance(data, dict):
            logger.warning("agents.yaml 顶层结构异常（非 dict），将使用空配置")
            return {}
        agents_list = data.get("agents", [])
        if not isinstance(agents_list, list):
            logger.warning("agents.yaml 的 agents 字段不是列表，跳过加载")
            return {}
        new_executors = {}
        for i, agent_data in enumerate(agents_list):
            if not isinstance(agent_data, dict):
                logger.warning("跳过 agents.yaml 第 %d 个无效条目（非 dict）: %s", i + 1, agent_data)
                continue
            if not agent_data.get("enabled", True):
                continue
            try:
                capability = AgentCapability(**agent_data)
            except Exception as e:
                logger.warning("跳过无效 Agent 配置: %s，错误: %s", agent_data.get("id", "?"), e)
                continue
            executor_cls = EXECUTOR_MAP.get(capability.type, CLIExecutor)
            new_executors[capability.id] = executor_cls(capability)
        return new_executors

    def load_from_config(self, config_path: Path):
        new_executors = self._build_executors(config_path)
        self.executors.update(new_executors)

    async def reload(self, config_path: Path):
        """重新加载配置，保留已有 Executor 的健康状态（快照替换，避免竞态）"""
        async with self._lock:
            old_health = {aid: ex.is_healthy for aid, ex in self.executors.items()}
            new_executors = self._build_executors(config_path)
            for aid, ex in new_executors.items():
                if aid in old_health:
                    ex.is_healthy = old_health[aid]
            self.executors = new_executors

    def get_executor(self, agent_id: str) -> Optional[BaseAgentExecutor]:
        return self.executors.get(agent_id)

    def get_healthy_agent_by_tag(self, tags: list[str]) -> Optional[str]:
        if not tags:
            return None
        tag_set = set(tags)
        for agent_id, executor in self.executors.items():
            if executor.is_healthy:
                agent_tags = set(executor.capability.tags)
                if tag_set & agent_tags:
                    return agent_id
        return None

    def get_healthy_agents_by_security_level(self, level: str) -> list[str]:
        """返回指定安全等级的所有健康 Agent ID 列表"""
        return [
            agent_id for agent_id, executor in self.executors.items()
            if executor.is_healthy and executor.capability.security_level == level
        ]

    def get_all_status(self) -> dict:
        return {
            agent_id: {
                "healthy": executor.is_healthy,
                "name": executor.capability.name,
                "type": executor.capability.type,
                "tags": executor.capability.tags,
            }
            for agent_id, executor in self.executors.items()
        }

    async def run_health_checks(self):
        tasks = [executor.health_check() for executor in self.executors.values()]
        await asyncio.gather(*tasks, return_exceptions=True)
