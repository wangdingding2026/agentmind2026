"""Query Understanding — Core LLM 查询改写：时间消歧、指代消解、意图分类"""

import json
import logging
from datetime import datetime, timezone

from agentmind.memory.types import RewrittenQuery

logger = logging.getLogger("agentmind")

_QU_SYSTEM_PROMPT = """你是查询理解器。分析用户消息，输出改写后的搜索查询。

任务：
1. 时间消歧："昨天/上周/那天/刚才" → 具体日期范围（今天是{date}）
2. 指代消解："那个bug/这个方案/上面的" → 替换为具体实体
3. 意图分类：factual（查事实）/ procedural（查步骤）/ episodic（查对话记录）
4. 实体提取：从消息中提取关键实体（Agent名、项目名、技术名词等）

只返回 JSON，不要其他内容：
{{"expanded_query": "改写后的查询", "date_filter": null, "entity_filters": [], "query_intent": "episodic", "confidence": 0.8}}

如果无法改写（Core LLM 不可用），返回原始查询 confidence=0.0。"""


class QueryUnderstanding:
    """使用 Core LLM 进行查询改写。Core LLM 不可用时透传原始查询。"""

    @staticmethod
    async def rewrite(raw_query: str, user_id: str = "") -> RewrittenQuery:
        try:
            from agentmind.core.core_llm import core_llm_chat

            today = datetime.now(timezone.utc).strftime("%Y年%m月%d日")
            prompt = _QU_SYSTEM_PROMPT.replace("{date}", today)

            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": raw_query},
            ]
            raw = await core_llm_chat(messages, temperature=0.1)
            if raw:
                return QueryUnderstanding._parse(raw, raw_query)
        except Exception as e:
            logger.debug("Query Understanding 失败: %s", e)

        return RewrittenQuery(expanded_query=raw_query, confidence=0.0)

    @staticmethod
    def _parse(raw: str, fallback_query: str) -> RewrittenQuery:
        # Lesson #17: 防御性 JSON 解析
        raw = raw.strip()
        if raw.startswith("```"):
            parts = raw.split("\n", 1)
            if len(parts) > 1:
                raw = parts[1]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError, AttributeError):
            logger.debug("Query Understanding JSON 解析失败: %s", raw[:200])
            return RewrittenQuery(expanded_query=fallback_query, confidence=0.0)

        if not isinstance(data, dict):
            return RewrittenQuery(expanded_query=fallback_query, confidence=0.0)

        expanded = str(data.get("expanded_query", fallback_query) or fallback_query)
        date_filter = data.get("date_filter")
        entity_filters = data.get("entity_filters", [])
        if isinstance(entity_filters, list):
            entity_filters = [str(e) for e in entity_filters if e]
        else:
            entity_filters = []
        intent = str(data.get("query_intent", "episodic") or "episodic")
        confidence = _safe_float(data.get("confidence"), 0.5)

        return RewrittenQuery(
            expanded_query=expanded,
            date_filter=date_filter if isinstance(date_filter, str) and date_filter else None,
            entity_filters=entity_filters,
            query_intent=intent,
            confidence=min(max(confidence, 0.0), 1.0),
        )


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (ValueError, TypeError):
        return default

from dataclasses import dataclass


@dataclass(frozen=True)
class ConversationHistoryQuery:
    intent: str
    time_range_start: str = ""
    time_range_end: str = ""
    current_session: bool = False
    limit: int = 50


def parse_conversation_history_query(
    message: str,
    *,
    now=None,
    timezone_name: str = "Asia/Shanghai",
) -> ConversationHistoryQuery | None:
    text = str(message or "").strip().lower()
    if not text:
        return None
    asks_history = any(
        token in text
        for token in ["聊过", "说过", "问过", "做过", "对话", "内容"]
    )
    if not asks_history:
        return None

    current_session = any(
        token in text
        for token in ["当前session", "当前 session", "当前会话", "本session", "本会话"]
    )
    if current_session:
        return ConversationHistoryQuery(
            intent="conversation_history",
            current_session=True,
        )

    from agentmind.services.time_service import local_day_bounds

    if "昨天" in text:
        start, end = local_day_bounds("yesterday", now=now, timezone_name=timezone_name)
        return ConversationHistoryQuery("conversation_history", start, end, False)
    if "今天" in text or "今日" in text:
        start, end = local_day_bounds("today", now=now, timezone_name=timezone_name)
        return ConversationHistoryQuery("conversation_history", start, end, False)
    return None
