"""MemoryRecallStrategy — 检测记忆召回意图，路由到 agentmind 自答。

不依赖 LLM，使用轻量级启发式规则：日期模式 + 召回意图词 + 历史指向词。
优先级 5，介于 ExplicitDirective(0) 和 RuleEngine(10) 之间。
"""

import re as _re

from agentmind.routing.context import RoutingContext
from agentmind.routing.strategies.base import RoutingStrategy, StrategyResult

# 日期模式：5月22日 / 5-22 / 2026-05-22 / 昨天 / 上周 / 那天 / 刚才 / 刚刚
_DATE_PATTERNS = _re.compile(
    r'\d{1,2}\s*月\s*\d{1,2}\s*日?|'
    r'\d{4}[/-]\d{1,2}[/-]\d{1,2}|'
    r'\d{1,2}[/-]\d{1,2}|'
    r'昨天|今天|上周|下周|那天|刚才|刚刚|之前那天'
)

# 记忆召回意图词
_RECALL_WORDS = _re.compile(
    r'聊天|聊过|说过|讨论过|检索|查找|搜索|回忆|记录|记得|想想|回想|会话|session'
)

# 历史指向词
_HISTORY_WORDS = _re.compile(
    r'之前|以前|上次|上回|历史|过去|之前聊|之前说|以前聊|以前说'
)

# 非记忆召回词：包含这些词的查询大概率是执行新任务而非查历史
_NON_RECALL_WORDS = _re.compile(
    r'新闻|天气|最新|实时|帮我|帮我写|帮我查|写代码|写个|做一个|'
    r'翻译|画一个|画个|生成|总结一下|分析一下'
)


class MemoryRecallStrategy(RoutingStrategy):
    """L2 策略：启发式检测记忆召回意图，路由到 agentmind。优先级 5。"""

    def __init__(self):
        super().__init__(name="memory_recall", priority=5)

    async def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        score = 0.0
        msg = ctx.raw_message

        # 0. 非记忆召回词：执行新任务的查询不应被拦截 (-0.5)
        if _NON_RECALL_WORDS.search(msg):
            score -= 0.5

        # 1. 日期模式 (+0.4)
        if _DATE_PATTERNS.search(msg):
            score += 0.4

        # 2. 召回意图词 (+0.3)
        if _RECALL_WORDS.search(msg):
            score += 0.3

        # 3. 历史指向词 (+0.2)
        if _HISTORY_WORDS.search(msg):
            score += 0.2

        # 4. L0 已检索到记忆 (+0.1, 追问场景)
        if ctx.memories:
            score += 0.1

        if score >= 0.6:
            return StrategyResult(
                agent_id="agentmind",
                confidence=0.85,
                reason=f"记忆召回(score={score:.1f})",
            )
        return None
