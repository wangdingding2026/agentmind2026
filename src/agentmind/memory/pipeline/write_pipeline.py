"""v4 写入流水线 — 10 步编排"""

import asyncio
import logging
from datetime import datetime, timezone

from agentmind.memory.types import MemoryEntry, MemoryType

logger = logging.getLogger("agentmind")


class WritePipeline:
    """10 步写入流水线。同步步骤(1-6,10) + 异步步骤(7-9, fire-and-forget)。"""

    def __init__(self, store):
        self._store = store
        self._pending_tasks: set = set()  # 防止异步任务被 GC

    async def execute(self, entry: MemoryEntry, force_new_conversation: bool = False) -> list[str]:
        """
        执行 10 步写入流水线。返回创建的所有 memory_id（chunking 可能产生多条）。
        """
        from agentmind.memory.components.content_hasher import ContentHasher
        from agentmind.memory.components.importance_scorer import ImportanceScorer
        from agentmind.memory.components.conversation_merger import ConversationMerger
        from agentmind.memory.components.chunker import Chunker
        from agentmind.memory.components.relation_extractor import RelationExtractor
        from agentmind.memory.components.core_memory_manager import CoreMemoryManager

        content = entry.content
        if not content or not content.strip():
            return []

        # 1. 类型识别
        if not entry.memory_type or entry.memory_type == MemoryType.EPISODIC:
            entry.memory_type = self._classify_type(content)

        # 2. simhash dedup
        hasher = ContentHasher()
        entry.content_hash = str(hasher.simhash(content))
        if await self._dedup_check(entry):
            logger.debug("dedup 命中，跳过写入: %s", entry.memory_id)
            return [entry.memory_id]

        # 3. importance 评分
        scorer = ImportanceScorer()
        entry.importance = scorer.score(content, entry.source_agent, entry.tags)

        # 4. conversation 归并
        if entry.memory_type == MemoryType.EPISODIC and entry.user_id:
            merger = ConversationMerger()
            conn = self._store._get_conn()
            try:
                entry.conversation_id = merger.find_or_create(
                    conn, entry.user_id, content, force_new=force_new_conversation
                )
                conn.commit()
            finally:
                conn.close()

        # 5. chunking
        chunker = Chunker()
        chunks = chunker.chunk(content)

        # 6. 同步 INSERT
        created_ids = []
        if len(chunks) == 1:
            await self._store.insert(entry)
            created_ids.append(entry.memory_id)
        else:
            for i, chunk_text in enumerate(chunks):
                chunk_entry = MemoryEntry(
                    memory_id=f"{entry.memory_id}/chunk{i}",
                    content=chunk_text,
                    summary=entry.summary[:1000],
                    source_agent=entry.source_agent,
                    source_task_id=entry.source_task_id,
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
                await self._store.insert(chunk_entry)
                created_ids.append(chunk_entry.memory_id)

        # 7-9. 异步步骤 (fire-and-forget，防止 GC)
        task = asyncio.create_task(self._async_enrich(entry, content, created_ids))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

        # 10. 容量检查
        await self._capacity_check()

        return created_ids if created_ids else [entry.memory_id]

    def _classify_type(self, content: str) -> MemoryType:
        """基于关键词的简单类型识别。"""
        if any(kw in content for kw in ["步骤", "怎么做", "如何", "怎样", "教程", "流程"]):
            return MemoryType.PROCEDURAL
        if any(kw in content for kw in ["什么是", "的定义", "的概念", "的原理"]):
            return MemoryType.SEMANTIC
        return MemoryType.EPISODIC

    async def _dedup_check(self, entry: MemoryEntry) -> bool:
        """检查是否已存在相似记忆。"""
        try:
            from agentmind.memory.types import SearchQuery
            results = await self._store.search(
                SearchQuery(query_text=entry.content[:200], user_id=entry.user_id, limit=5)
            )
            from agentmind.memory.components.content_hasher import ContentHasher
            current_hash = int(entry.content_hash)
            for r in results:
                try:
                    existing_hash = int(r.entry.content_hash)
                    if ContentHasher.is_similar(current_hash, existing_hash, threshold=3):
                        return True
                except (ValueError, TypeError):
                    pass
        except Exception:
            pass
        return False

    async def _async_enrich(self, entry: MemoryEntry, content: str, created_ids: list[str]):
        """异步富化：embedding 生成 + 关系抽取 + Core Memory 候选检测。"""
        # 7. embedding 生成
        try:
            from agentmind.storage.memory import _generate_embedding, _embedding_to_blob
            emb = await _generate_embedding(content)
            if emb and is_vec_available():
                blob = _embedding_to_blob(emb)
                conn = self._store._get_conn()
                try:
                    for mid in created_ids:
                        try:
                            conn.execute(
                                "INSERT OR REPLACE INTO vec_memory(memory_id, embedding) VALUES (?, ?)",
                                (mid, blob),
                            )
                        except Exception:
                            pass
                    conn.commit()
                finally:
                    conn.close()
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
                conn = self._store._get_conn()
                try:
                    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    for head, rel, target, tail_id, conf in all_relations:
                        try:
                            conn.execute(
                                """INSERT OR IGNORE INTO memory_relations
                                   (user_id, head_entity, relation, tail_entity,
                                    head_memory_id, tail_memory_id, confidence, ts, created_at)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (entry.user_id, head, rel, target, head, tail_id, conf, now, now),
                            )
                        except Exception:
                            pass
                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:
            logger.debug("异步关系抽取失败: %s", e)

        # 9. Core Memory 候选检测
        try:
            from agentmind.memory.components.core_memory_manager import CoreMemoryManager
            if CoreMemoryManager.is_candidate(entry):
                await CoreMemoryManager.upsert(self._store, entry)
        except Exception as e:
            logger.debug("异步 Core Memory 候选失败: %s", e)

    async def _capacity_check(self):
        """容量检查：超过 max_entries 时 LRU 淘汰。"""
        try:
            from agentmind.storage.memory import _load_settings
            settings = _load_settings()
            max_entries = settings.get("memory", {}).get("max_entries", 10000)
            total = await self._store.count()
            if total >= max_entries:
                evict_count = max(1, int(total * 0.1))
                conn = self._store._get_conn()
                try:
                    rows = conn.execute(
                        "SELECT memory_id FROM memory_entries ORDER BY created_at ASC LIMIT ?",
                        (evict_count,),
                    ).fetchall()
                    for r in rows:
                        mid = r["memory_id"]
                        conn.execute("DELETE FROM memory_entries WHERE memory_id=?", (mid,))
                        try:
                            conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (mid,))
                        except Exception:
                            pass
                        if is_vec_available():
                            try:
                                conn.execute("DELETE FROM vec_memory WHERE memory_id=?", (mid,))
                            except Exception:
                                pass
                    conn.commit()
                    logger.info("LRU 淘汰：%d 条", len(rows))
                finally:
                    conn.close()
        except Exception as e:
            logger.debug("容量检查失败: %s", e)


def is_vec_available() -> bool:
    try:
        from agentmind.storage.db import is_vec_available as _f
        return _f()
    except Exception:
        return False
