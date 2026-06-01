"""LLM-backed team knowledge extraction."""

from __future__ import annotations

import json
import logging
import re
import uuid

from agentmind.core.core_llm import core_llm_chat
from agentmind.memory.types import MemoryEntry

logger = logging.getLogger("agentmind")

ALLOWED_KNOWLEDGE_TYPES = {
    "task_conclusion",
    "team_decision",
    "user_preference",
    "long_term_fact",
    "procedure",
}

_PROMPT = """你是 AgentMind 的团队知识库抽取器。只判断当前新记忆是否应沉淀为团队长期知识。

沉淀标准：
1. 对未来 Agent 协作有复用价值。
2. 是稳定事实、任务结论、团队决策、用户偏好或流程知识。
3. 不是临时聊天、一次性日志、未确认猜测或纯过程信息。
4. 必须给出原文证据 evidence。

knowledge_type 只能取：
- task_conclusion
- team_decision
- user_preference
- long_term_fact
- procedure

如果应沉淀，返回：
{"should_promote": true, "knowledge_type": "...", "title": "...", "content": "...", "confidence": 0.0-1.0, "evidence": "..."}

如果不应沉淀，返回：
{"should_promote": false, "reason": "..."}

只返回 JSON，不要解释。"""


class KnowledgeExtractor:
    """Extract durable team knowledge from newly written memory cards."""

    async def extract(self, entry: MemoryEntry, source_memory_id: str) -> dict | None:
        text = self._source_text(entry)
        if not text.strip():
            return None
        messages = [
            {"role": "system", "content": _PROMPT},
            {
                "role": "user",
                "content": (
                    f"memory_id: {source_memory_id}\n"
                    f"user_id: {entry.user_id}\n"
                    f"source_agent: {entry.source_agent}\n"
                    f"source_task_id: {entry.source_task_id}\n"
                    f"content:\n{text[:4000]}"
                ),
            },
        ]
        raw = await core_llm_chat(messages, temperature=0.1)
        if not raw:
            return None
        data = self._parse_json(raw)
        if not isinstance(data, dict) or not data.get("should_promote"):
            return None
        return self._normalize(data, entry, source_memory_id, text)

    def _normalize(
        self,
        data: dict,
        entry: MemoryEntry,
        source_memory_id: str,
        source_text: str,
    ) -> dict | None:
        knowledge_type = str(data.get("knowledge_type", "")).strip()
        if knowledge_type not in ALLOWED_KNOWLEDGE_TYPES:
            return None
        title = str(data.get("title", "")).strip()
        content = str(data.get("content", "")).strip()
        evidence = str(data.get("evidence", "")).strip()
        confidence = _safe_float(data.get("confidence"), 0.0)
        if not title or not content or not evidence:
            return None
        if confidence < 0.6 or confidence > 1.0:
            return None
        if evidence not in source_text:
            return None

        status = "active" if confidence >= 0.85 else "pending"
        return {
            "knowledge_id": f"kb-{uuid.uuid4().hex[:16]}",
            "user_id": entry.user_id,
            "knowledge_type": knowledge_type,
            "title": title[:300],
            "content": content[:2000],
            "source_memory_id": source_memory_id,
            "source_agent": entry.source_agent,
            "source_task_id": entry.source_task_id,
            "confidence": confidence,
            "status": status,
            "evidence": evidence[:1000],
            "tags": list(entry.tags or []),
        }

    @staticmethod
    def _source_text(entry: MemoryEntry) -> str:
        return "\n\n".join(part for part in [entry.summary, entry.content] if part)

    @staticmethod
    def _parse_json(raw: str) -> dict | None:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            text = text.rsplit("\n```", 1)[0] if "```" in text else text
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.S)
            if not match:
                logger.debug("Knowledge extraction JSON parse failed: %s", raw[:200])
                return None
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                logger.debug("Knowledge extraction JSON parse failed: %s", raw[:200])
                return None


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
