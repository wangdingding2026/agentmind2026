"""关系抽取 — 从记忆内容中提取实体关系（简单正则，M4 升级 NER+RE）"""

import re

_RELATION_PATTERNS = [
    (re.compile(r'(?:参考|参照|参见|引用|基于)\s*[：:]?\s*(.+)'), "references"),
    (re.compile(r'(?:依赖|需要|要求)\s*[：:]?\s*(.+)'), "depends_on"),
    (re.compile(r'(?:修复|解决|修复了|解决了)\s*[：:]?\s*(.+)'), "fixes"),
    (re.compile(r'(?:属于|是)\s*(.+?)(?:的|的一部分)'), "part_of"),
    (re.compile(r'(?:替代|取代|替换|代替)\s*[：:]?\s*(.+)'), "replaces"),
]


class RelationExtractor:
    """从记忆内容中提取关系。M1 用正则，M4 升级为 NER+RE 模型。"""

    async def extract(self, memory_id: str, content: str) -> list[tuple[str, str, str, str, float]]:
        """
        返回 (head_memory_id, relation, tail_entity, tail_memory_id, confidence) 列表。
        head_memory_id 是当前 memory_id，tail_entity 是从 content 中提取的目标实体名。
        """
        relations = []
        for pattern, rel_type in _RELATION_PATTERNS:
            for m in pattern.finditer(content):
                target = m.group(1).strip()
                if target and len(target) <= 80:
                    relations.append((memory_id, rel_type, target, "", 0.6))
        return relations
