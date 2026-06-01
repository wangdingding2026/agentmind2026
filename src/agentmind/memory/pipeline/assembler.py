"""Context Assembler — 组装检索结果为注入 prompt 的上下文字符串（≤8KB）"""

import logging
from dataclasses import dataclass

from agentmind.memory.types import SearchResult

logger = logging.getLogger("agentmind")


@dataclass
class AssembledContext:
    full_text: str
    core_section: str
    working_section: str
    recall_section: str
    total_bytes: int
    truncated: bool


class ContextAssembler:

    def __init__(self, max_bytes: int = 8192):
        self.max_bytes = max_bytes

    def assemble(
        self,
        core_memory_text: str,
        working_memory_rounds: list[dict],
        recall_results: list[SearchResult],
        knowledge_items: list[dict] | None = None,
        max_bytes: int | None = None,
    ) -> AssembledContext:
        limit = max_bytes or self.max_bytes
        truncated = False

        # 1. Core Memory 截断（≤2KB）
        core = self._truncate_bytes(core_memory_text, 2048)

        # 2. Working Memory 格式化（≤2KB）
        working_parts = []
        for r in working_memory_rounds[-5:]:  # 最多 5 轮
            user_msg = (r.get("user") or "")[:200]
            asst_msg = (r.get("assistant") or "")[:300]
            working_parts.append(f"[用户]: {user_msg}\n[Agent]: {asst_msg}")
        working = "\n---\n".join(working_parts)
        working = self._truncate_bytes(working, 2048)

        # 3. Team Knowledge 格式化（≤2KB）
        knowledge_parts = []
        for item in (knowledge_items or [])[:10]:
            knowledge_type = item.get("knowledge_type") or "knowledge"
            title = (item.get("title") or "")[:200]
            content = (item.get("content") or "")[:500]
            if title and content:
                knowledge_parts.append(f"[{knowledge_type}] {title}\n{content}")
        knowledge = self._truncate_bytes("\n---\n".join(knowledge_parts), 2048)

        # 4. Recall 去重 + 截断
        deduped = self._dedup_by_hash(recall_results)

        # 5. Recall 格式化
        recall_parts = []
        for r in deduped:
            e = r.entry
            content = (e.content or "")[:200]
            summary = (e.summary or "")[:300]
            agent = e.source_agent or "unknown"
            recall_parts.append(f"[{agent}] 问：「{content}」→ {summary}")

        recall = "\n".join(recall_parts)

        # 5. 三段拼接
        sections = []
        if core.strip():
            sections.append(f"[用户画像]\n{core}")
        if working.strip():
            sections.append(f"[近期对话]\n{working}")
        if knowledge.strip():
            sections.append(f"[团队知识库]\n{knowledge}")
        if recall.strip():
            sections.append(f"[相关记忆]\n{recall}")

        full = "\n\n".join(sections)

        # 6. 字节级硬截断
        full_bytes = len(full.encode("utf-8"))
        if full_bytes > limit:
            truncated = True
            # 从 Recall 部分逐条丢弃
            while full_bytes > limit and recall_parts:
                recall_parts.pop()
                recall = "\n".join(recall_parts)
                sections = []
                if core.strip():
                    sections.append(f"[用户画像]\n{core}")
                if working.strip():
                    sections.append(f"[近期对话]\n{working}")
                if knowledge.strip():
                    sections.append(f"[团队知识库]\n{knowledge}")
                if recall.strip():
                    sections.append(f"[相关记忆]\n{recall}")
                full = "\n\n".join(sections)
                full_bytes = len(full.encode("utf-8"))
            # 如果还是超限，硬截断
            if full_bytes > limit:
                full = full.encode("utf-8")[:limit].decode("utf-8", errors="replace")
                full_bytes = len(full.encode("utf-8"))

        recall_section = f"[相关记忆]\n{recall}" if recall.strip() else ""

        return AssembledContext(
            full_text=full,
            core_section=core,
            working_section=working,
            recall_section=recall_section,
            total_bytes=full_bytes,
            truncated=truncated,
        )

    @staticmethod
    def _dedup_by_hash(results: list[SearchResult]) -> list[SearchResult]:
        seen_hashes: set[str] = set()
        deduped = []
        try:
            from agentmind.memory.components.content_hasher import ContentHasher
            hasher = ContentHasher()
            for r in results:
                h = r.entry.content_hash
                if not h:
                    deduped.append(r)
                    continue
                # 检查是否与已有结果相似
                is_dup = False
                for seen in seen_hashes:
                    try:
                        if hasher.is_similar(int(h), int(seen), threshold=3):
                            is_dup = True
                            break
                    except (ValueError, TypeError):
                        pass
                if not is_dup:
                    seen_hashes.add(h)
                    deduped.append(r)
        except Exception:
            return results
        return deduped

    @staticmethod
    def _truncate_bytes(text: str, max_bytes: int) -> str:
        if not text:
            return ""
        b = text.encode("utf-8")
        if len(b) <= max_bytes:
            return text
        return b[:max_bytes].decode("utf-8", errors="replace")
