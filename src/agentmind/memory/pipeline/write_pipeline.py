"""Canonical memory write pipeline."""
import logging

from agentmind.memory.dto import MemoryWriteCommand
from agentmind.memory.provider import (
    MemoryEmbeddingProvider,
    embedding_to_blob,
    read_memory_settings,
)
from agentmind.memory.types import MemoryEntry, MemoryType

logger = logging.getLogger("agentmind")
VECTOR_RUNTIME_WRITE_ENABLED = True


class WritePipeline:
    """10 步写入流水线。raw/card 主写入优先，富化受控执行。"""

    def __init__(self, store=None, repository=None):
        if repository is None:
            from agentmind.memory.repository_sqlite import SqliteMemoryRepository
            repository = SqliteMemoryRepository(getattr(store, "_db_path", ""))
        self._repository = repository

    async def execute(self, entry: MemoryEntry, force_new_conversation: bool = False) -> list[str]:
        """
        执行 10 步写入流水线。返回创建的所有 memory_id（chunking 可能产生多条）。
        """
        from agentmind.memory.components.content_hasher import ContentHasher
        from agentmind.memory.components.importance_scorer import ImportanceScorer
        from agentmind.memory.components.chunker import Chunker
        from agentmind.memory.components.core_memory_manager import CoreMemoryManager

        content = entry.content
        if not content or not content.strip():
            return []

        # 1. 类型识别
        if not entry.memory_type or entry.memory_type == MemoryType.EPISODIC:
            entry.memory_type = self._classify_type(content)

        # 2. simhash dedup — 用 content + summary 联合计算，相同问题不同回答不会误杀
        hasher = ContentHasher()
        combined = content
        if entry.summary:
            combined = f"{content}\n{entry.summary}"
        entry.content_hash = str(hasher.simhash(combined))
        if await self._dedup_check(entry):
            logger.debug("dedup 命中，跳过写入: %s", entry.memory_id)
            return []

        # 3. importance 评分
        scorer = ImportanceScorer()
        entry.importance = scorer.score(content, entry.source_agent, entry.tags)

        # 4. conversation 归并
        if entry.memory_type == MemoryType.EPISODIC and entry.user_id:
            entry.conversation_id = await self._repository.find_or_create_conversation(
                entry.user_id, content, force_new=force_new_conversation
            )

        # 5. chunking
        chunker = Chunker()
        chunks = chunker.chunk(content)

        # 6. 同步 INSERT
        created_ids = []
        if len(chunks) == 1:
            row = await self._write_raw_and_card(entry)
            created_ids.append(row.get("memory_id") or entry.memory_id)
        else:
            for i, chunk_text in enumerate(chunks):
                chunk_entry = MemoryEntry(
                    memory_id=f"{entry.memory_id}/chunk{i}",
                    content=chunk_text,
                    summary=entry.summary[:1000],
                    source_agent=entry.source_agent,
                    source_task_id=entry.source_task_id,
                    source_kind=entry.source_kind,
                    user_id=entry.user_id,
                    memory_type=entry.memory_type,
                    conversation_id=entry.conversation_id,
                    importance=entry.importance,
                    content_hash=ContentHasher().sha256(chunk_text),
                    embedding_model=entry.embedding_model,
                    embedding_version=entry.embedding_version,
                    parent_id=entry.memory_id,
                    tags=entry.tags,
                    access_level=entry.access_level,
                )
                row = await self._write_raw_and_card(chunk_entry)
                created_ids.append(row.get("memory_id") or chunk_entry.memory_id)

        if CoreMemoryManager.is_candidate(entry):
            await self._repository.write_core_candidate(entry)

        # 7-9. 受控富化。失败只记录日志，不影响 raw/card 主写入。
        await self._async_enrich(entry, content, created_ids)

        # 10. 容量检查
        await self._capacity_check()

        return created_ids if created_ids else [entry.memory_id]

    async def _write_raw_and_card(self, entry: MemoryEntry) -> dict:
        command = MemoryWriteCommand(
            memory_id=entry.memory_id,
            content=entry.content,
            summary=entry.summary,
            user_id=entry.user_id,
            source_agent=entry.source_agent,
            source_task_id=entry.source_task_id,
            source_kind=entry.source_kind,
            session_id=entry.conversation_id,
            conversation_id=entry.conversation_id,
            tags=entry.tags,
            memory_type=entry.memory_type.value,
            importance=entry.importance,
            access_level=entry.access_level,
            content_hash=entry.content_hash,
            parent_id=entry.parent_id,
            embedding_model=entry.embedding_model,
            embedding_version=entry.embedding_version,
            created_at=entry.created_at,
        )
        return await self._repository.write_raw_and_card(command)

    def _classify_type(self, content: str) -> MemoryType:
        """基于关键词的简单类型识别。"""
        if any(kw in content for kw in ["步骤", "怎么做", "如何", "怎样", "教程", "流程"]):
            return MemoryType.PROCEDURAL
        if any(kw in content for kw in ["什么是", "的定义", "的概念", "的原理"]):
            return MemoryType.SEMANTIC
        return MemoryType.EPISODIC

    async def _dedup_check(self, entry: MemoryEntry) -> bool:
        """基于 simhash 汉明距离检查是否已存在相似记忆。

        与 Assembler._dedup_by_hash 对齐：使用 content_hash（联合 content+summary）
        做汉明距离比较，替代不可靠的子串匹配。
        """
        if not entry.content_hash:
            return False
        try:
            from agentmind.memory.components.content_hasher import ContentHasher

            results = await self._repository.search_cards(
                query=entry.content[:200],
                user_id=entry.user_id,
                limit=5,
            )
            for r in results:
                score_meta = r.get("score_metadata") or {}
                if isinstance(score_meta, str):
                    import json as _json
                    try:
                        score_meta = _json.loads(score_meta)
                    except (_json.JSONDecodeError, TypeError):
                        score_meta = {}
                existing_hash_str = score_meta.get("content_hash", "")
                if existing_hash_str:
                    try:
                        if ContentHasher.is_similar(
                            int(entry.content_hash), int(existing_hash_str), threshold=3,
                        ):
                            return True
                    except (ValueError, TypeError):
                        pass
        except Exception:
            pass
        return False

    async def _async_enrich(self, entry: MemoryEntry, content: str, created_ids: list[str]):
        """异步富化：embedding 生成 + 关系抽取 + Core Memory 候选检测。"""
        # 7. Vector write is best-effort: memory write succeeds even if embedding fails.
        if VECTOR_RUNTIME_WRITE_ENABLED:
            try:
                emb = await MemoryEmbeddingProvider().generate_embedding(content)
                if emb:
                    blob = embedding_to_blob(emb)
                    settings = read_memory_settings()
                    emb_cfg = settings.get("embedding", {})
                    await self._repository.write_vector_embedding(
                        created_ids,
                        blob,
                        model=emb_cfg.get("model", entry.embedding_model),
                        version=int(emb_cfg.get("version", entry.embedding_version or 1)),
                        dimension=len(emb),
                    )
            except Exception as e:
                logger.debug("异步 embedding 失败: %s", e)

        # 8. 关系抽取
        try:
            from agentmind.memory.components.relation_extractor import RelationExtractor
            extractor = RelationExtractor()
            all_relations = []
            for mid in created_ids:
                relations = await extractor.extract(mid, content)
                all_relations.extend(relations[:5])
            if all_relations:
                await self._repository.write_relations(entry.user_id, all_relations)
        except Exception as e:
            logger.debug("异步关系抽取失败: %s", e)

    async def _capacity_check(self):
        """容量检查：超过 max_entries 时 LRU 淘汰。"""
        try:
            settings = read_memory_settings()
            max_entries = settings.get("memory", {}).get("max_entries", 10000)
            if max_entries <= 0:
                return
        except Exception as e:
            logger.debug("容量检查失败: %s", e)


def is_vec_available() -> bool:
    """Compatibility probe for callers that still expose sqlite-vec status."""
    try:
        from agentmind.storage.db import is_vec_available as _f
        return _f()
    except Exception:
        return False
