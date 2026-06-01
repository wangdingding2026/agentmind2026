import asyncio
import json
import logging

import httpx

from agentmind.routing.context import RoutingContext
from agentmind.routing.strategies.base import RoutingStrategy, StrategyResult

logger = logging.getLogger("agentmind")

_LLM_SEMAPHORE = asyncio.Semaphore(3)

_DISPATCH_PROMPT = (
    "你是 AgentMind，一个 Agent 管理中枢。分析用户消息，决定路由策略。\n"
    "\n"
    "AgentMind 本身不做 AI 推理，职责是：路由指令到后端 Agent、管理进程、维护共享记忆、桥接飞书。\n"
    "\n"
    "规则：\n"
    "1. 寒暄/自我介绍/「你能做什么」/Agent推荐 → action: reply，简短回复（≤150字）\n"
    "2. 记忆检索/历史查询/「还记得」/「聊过什么」/「今天/昨天聊过什么」 → action: route，agent_id=agentmind，confidence=0.9\n"
    "3. 需要写代码/查资料/搜索/执行任务 → action: route，指定最合适的 agent_id\n"
    "4. 不确定 → action: route，选择最通用的 agent\n"
    "\n"
    "只返回 JSON，不要其他内容：\n"
    '{"action": "reply", "reply": "回复内容"} 或\n'
    '{"action": "route", "agent_id": "xxx", "confidence": 0.9, "reason": "原因"}'
)


class LLMRoutingStrategy(RoutingStrategy):
    """旧版 freeform LLM 路由，仅保留给显式兼容场景。

    默认策略链使用 SemanticIntentStrategy，不再让 LLM 直接生成最终 reply_text。
    """

    def __init__(self, agent_registry, settings: dict):
        super().__init__(name="llm_routing", priority=20)
        self._registry = agent_registry
        self._settings = settings

    async def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        cfg = self._get_cfg()
        if not cfg.get("enabled") or not cfg.get("endpoint"):
            return None

        candidates = ctx.candidates
        if not candidates and not ctx.security_flagged:
            candidates = [
                aid for aid, ex in self._registry.executors.items() if ex.is_healthy
            ]
        if not candidates:
            return None

        lines = []
        for aid in candidates:
            ex = self._registry.get_executor(aid)
            if ex:
                c = ex.capability
                tags = ", ".join(c.tags) if c.tags else ""
                lines.append(f"- {aid} ({c.name}): {c.description or ''} [tags: {tags}]")
        agents_desc = "\n".join(lines)
        valid_ids = set(candidates)

        memory_block = ""
        if ctx.memories:
            mem_lines = []
            for m in ctx.memories:
                content = m.get("content", "")[:200]
                mem_type = m.get("memory_type", "")
                mem_lines.append(f"- [{mem_type}] {content}")
            if mem_lines:
                memory_block = "相关记忆：\n" + "\n".join(mem_lines) + "\n\n"

        prompt = (
            f"{_DISPATCH_PROMPT}\n"
            f"可用 Agent：\n{agents_desc}\n"
            f"有效 ID：{', '.join(sorted(valid_ids))}\n\n"
            f"{memory_block}"
            f"用户消息：{ctx.raw_message}"
        )

        try:
            async with _LLM_SEMAPHORE:
                resp = await asyncio.wait_for(
                    self._call_llm(prompt, cfg),
                    timeout=cfg.get("timeout_seconds", 5),
                )
        except Exception:
            logger.debug("LLM 语义路由调用失败，弃权")
            return None

        if resp is None:
            return None

        action = resp.get("action", "")
        if action == "reply" and resp.get("reply"):
            return StrategyResult(
                agent_id="agentmind", confidence=0.9,
                reason=f"LLM 自答: {resp['reply'][:60]}",
                reply_text=str(resp["reply"]),
            )
        if action == "route" and resp.get("agent_id") in valid_ids:
            return StrategyResult(
                agent_id=resp["agent_id"],
                confidence=float(resp.get("confidence", 0.8)),
                reason=f"LLM 路由: {resp.get('reason', '')}"[:100],
            )
        return None

    def _get_cfg(self) -> dict:
        cfg = self._settings.get("core_llm", {})
        if not cfg:
            cfg = self._settings.get("semantic_router", {})
        return cfg if isinstance(cfg, dict) else {}

    async def _call_llm(self, prompt: str, cfg: dict) -> dict | None:
        endpoint = cfg["endpoint"]
        if "/chat/completions" not in endpoint:
            endpoint = endpoint.rstrip("/") + "/v1/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=cfg.get("timeout_seconds", 5)) as client:
                r = await client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {cfg.get('api_key', '')}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": cfg.get("model", ""),
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                    },
                )
                if r.status_code == 200:
                    data = r.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                    content = content.strip()
                    if content.startswith("```"):
                        content = content.split("\n", 1)[-1].rsplit("\n```", 1)[0] if "```" in content else content
                    return json.loads(content)
        except Exception:
            pass
        return None
