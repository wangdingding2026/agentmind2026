import asyncio
import json
import logging

import httpx

from agentmind.routing.context import RoutingContext
from agentmind.routing.semantic_intent import SemanticIntent, SemanticIntentType
from agentmind.routing.strategies.base import RoutingStrategy, StrategyResult

logger = logging.getLogger("agentmind")

_LLM_SEMAPHORE = asyncio.Semaphore(3)
_MIN_CONFIDENCE = 0.7

_SEMANTIC_INTENT_PROMPT = """你是 AgentMind 的结构化语义路由器。你的唯一职责是判断用户消息的语义意图，不能直接回答用户问题。

AgentMind 是 Agent 管理中枢，负责路由指令到后端 Agent、管理进程、维护共享记忆、桥接飞书。

必须只返回 JSON，不要返回 Markdown、解释或自然语言答案。
尤其注意：历史查询、记忆查询、今天/昨天/当前 session 聊过什么，都不要直接生成历史答案，只能输出 intent=conversation_history。

可用 intent：
- conversation_history：用户询问历史对话、记忆、今天/昨天/当前会话聊过什么、还记得什么。
- agent_task：用户要求执行实际任务，例如搜索、查询天气、写代码、分析资料、调用工具。
- agentmind_capability：用户询问 AgentMind 或系统能不能做什么、有什么能力、如何工作。
- smalltalk：寒暄、问候、简单闲聊。
- unknown：无法确定。

输出 JSON schema：
{
  "intent": "conversation_history|agent_task|agentmind_capability|smalltalk|unknown",
  "confidence": 0.0,
  "target_agent": "",
  "time_scope": "none|current_session|today|yesterday|recent|explicit_date|all",
  "current_session": false,
  "explicit_date": "",
  "agent_filter": "",
  "requested_format": "answer_only|qa_summary|topic_summary|list",
  "reason": ""
}

路由判断要求：
- “今天都聊过什么内容，帮我总结一下”“我们今天聊过什么”“昨天做过什么”“当前session聊过什么”必须是 conversation_history。
- “你能查询天气吗？”是 agentmind_capability。
- “帮我查今天上海天气”是 agent_task，并在 target_agent 中选择最合适且有效的 agent_id。
- target_agent 只能从有效 ID 中选择；不需要后端 Agent 的 intent 留空。
"""


class SemanticIntentStrategy(RoutingStrategy):
    """结构化语义路由：LLM 只产出 intent，不产出最终用户答案。"""

    def __init__(self, agent_registry, settings: dict):
        super().__init__(name="semantic_intent", priority=20)
        self._registry = agent_registry
        self._settings = settings

    async def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        cfg = self._get_cfg()
        if not cfg.get("enabled") or not cfg.get("endpoint"):
            return None

        valid_agent_ids = self._valid_agent_ids(ctx)
        prompt = self._build_prompt(ctx, valid_agent_ids)

        try:
            async with _LLM_SEMAPHORE:
                payload = await asyncio.wait_for(
                    self._call_llm(prompt, cfg),
                    timeout=cfg.get("timeout_seconds", 5),
                )
        except Exception:
            logger.debug("结构化语义路由调用失败，弃权", exc_info=True)
            return None

        semantic_intent = SemanticIntent.from_llm_payload(payload or {})
        if semantic_intent.intent == SemanticIntentType.UNKNOWN:
            return None
        if semantic_intent.confidence < _MIN_CONFIDENCE:
            return None

        result = self._to_strategy_result(semantic_intent, valid_agent_ids)
        if result is None:
            return None

        ctx.semantic_intent = semantic_intent
        return result

    def _to_strategy_result(
        self,
        semantic_intent: SemanticIntent,
        valid_agent_ids: set[str],
    ) -> StrategyResult | None:
        intent_type = semantic_intent.intent
        if intent_type == SemanticIntentType.CONVERSATION_HISTORY:
            return self._agentmind_result(semantic_intent)
        if intent_type == SemanticIntentType.AGENTMIND_CAPABILITY:
            return self._agentmind_result(semantic_intent)
        if intent_type == SemanticIntentType.SMALLTALK:
            return self._agentmind_result(semantic_intent)
        if intent_type == SemanticIntentType.AGENT_TASK:
            target_agent = semantic_intent.target_agent
            if not target_agent or target_agent not in valid_agent_ids:
                return None
            return StrategyResult(
                agent_id=target_agent,
                confidence=semantic_intent.confidence,
                reason=self._reason(semantic_intent),
                semantic_intent=semantic_intent,
            )
        return None

    def _agentmind_result(self, semantic_intent: SemanticIntent) -> StrategyResult:
        return StrategyResult(
            agent_id="agentmind",
            confidence=semantic_intent.confidence,
            reason=self._reason(semantic_intent),
            reply_text="",
            semantic_intent=semantic_intent,
        )

    def _reason(self, semantic_intent: SemanticIntent) -> str:
        reason = semantic_intent.reason.strip()
        suffix = f": {reason}" if reason else ""
        return f"语义意图: {semantic_intent.intent.value}{suffix}"[:100]

    def _valid_agent_ids(self, ctx: RoutingContext) -> set[str]:
        if ctx.candidates:
            candidates = ctx.candidates
        elif ctx.security_flagged:
            candidates = []
        else:
            candidates = list(self._registry.executors.keys())

        valid = set()
        for agent_id in candidates:
            executor = self._registry.get_executor(agent_id)
            if executor and executor.is_healthy:
                valid.add(agent_id)
        return valid

    def _build_prompt(self, ctx: RoutingContext, valid_agent_ids: set[str]) -> str:
        agent_lines = []
        for agent_id in sorted(valid_agent_ids):
            executor = self._registry.get_executor(agent_id)
            if not executor:
                continue
            capability = executor.capability
            tags = ", ".join(capability.tags) if capability.tags else ""
            agent_lines.append(
                f"- {agent_id} ({capability.name}): {capability.description or ''} [tags: {tags}]"
            )

        memory_block = ""
        if ctx.memories:
            memory_lines = []
            for memory in ctx.memories[:5]:
                content = str(memory.get("content", ""))[:200]
                memory_type = str(memory.get("memory_type", ""))
                memory_lines.append(f"- [{memory_type}] {content}")
            if memory_lines:
                memory_block = "相关记忆（仅用于判断意图，不可作为最终答案）：\n"
                memory_block += "\n".join(memory_lines)
                memory_block += "\n\n"

        return (
            f"{_SEMANTIC_INTENT_PROMPT}\n\n"
            f"可用 Agent：\n{chr(10).join(agent_lines) if agent_lines else '(无)'}\n"
            f"有效 ID：{', '.join(sorted(valid_agent_ids)) if valid_agent_ids else '(无)'}\n\n"
            f"{memory_block}"
            f"用户消息：{ctx.raw_message}"
        )

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
                response = await client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {cfg.get('api_key', '')}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": cfg.get("model", ""),
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.0,
                    },
                )
                if response.status_code != 200:
                    return None
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                return json.loads(_strip_code_fence(str(content).strip()))
        except Exception:
            logger.debug("结构化语义路由响应解析失败", exc_info=True)
            return None


def _strip_code_fence(content: str) -> str:
    if not content.startswith("```"):
        return content
    lines = content.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
