"""重要性评分 — 规则驱动，上限 1.0"""

import re

from agentmind.memory.provider import read_agent_credibility

# 用户强调关键词
_EMPHASIS_WORDS = re.compile(r'记住|重要|务必|关键|必须|一定要|千万别|千万别忘')

# 命名实体简单检测（中文人名/地名/组织名等）
_ENTITY_RE = re.compile(
    r'[一-鿿]{2,4}(?:公司|团队|系统|平台|项目|部门|模块|接口|服务)'
    r'|[A-Z][a-z]+(?:\s[A-Z][a-z]+)?'
)

# 事实性陈述特征
_FACT_INDICATORS = re.compile(
    r'是|有|在|用|需要|应该|可以|会|能|必须|包括|包含|属于|等于|大于|小于'
    r'|config|api|bug|error|fix|feature|deploy|release|version'
)


class ImportanceScorer:
    """规则驱动的重要性评分（0-1），不依赖 LLM。"""

    @staticmethod
    def score(content: str, source_agent: str = "", tags: list[str] | None = None) -> float:
        score = 0.0

        # 用户强调词 (+0.3)
        if _EMPHASIS_WORDS.search(content):
            score += 0.3

        # 命名实体 (+0.2)
        if _ENTITY_RE.search(content):
            score += 0.2

        # 内容长度 (+0.2)：太短或太长都不重要
        length = len(content)
        if 50 <= length <= 2000:
            score += 0.2
        elif length > 2000:
            score += 0.1

        # 事实性 (+0.2)
        if _FACT_INDICATORS.search(content.lower()):
            score += 0.2

        # Agent 可信度 (+0.1)
        cred = ImportanceScorer._get_credibility(source_agent)
        score += 0.1 * cred

        return min(score, 1.0)

    @staticmethod
    def _get_credibility(agent_id: str) -> float:
        if not agent_id:
            return 0.5
        try:
            return read_agent_credibility(agent_id)
        except Exception:
            return 0.5
