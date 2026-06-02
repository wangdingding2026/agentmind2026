"""MemoryService — canonical memory engine entry point."""

import logging

from agentmind.memory.dto import MemoryContext
from agentmind.memory.provider import MemoryEmbeddingProvider
from agentmind.memory.types import MemoryEntry, MemoryType
from agentmind.services.config_service import ConfigService

logger = logging.getLogger("agentmind")


class MemoryService:
    """Canonical memory service for write, retrieval, stats, cleanup, and sessions."""

    def __init__(self, store=None, repository=None):
        if repository is None:
            from agentmind.memory.repository_sqlite import SqliteMemoryRepository
            repository = SqliteMemoryRepository(getattr(store, "_db_path", ""))
        self._repository = repository

    # ── 写入 ──

    async def write_memory(
        self, entry: dict, generate_embedding: bool = True, user_id: str = ""
    ) -> int:
        """写入记忆，返回写入条数（chunking 可能产生多条）。"""
        from agentmind.memory.pipeline.write_pipeline import WritePipeline

        mem = MemoryEntry.from_dict(entry)
        if user_id:
            mem.user_id = user_id

        # 检查是否需要 force_new_conversation（用户切换了 session 或刚执行 /new）
        force_new = False
        if mem.user_id:
            if await self._repository.consume_force_new(mem.user_id):
                force_new = True
            elif mem.memory_type == MemoryType.EPISODIC:
                _, created = await self._repository.ensure_active_session(mem.user_id)
                force_new = created

        pipeline = WritePipeline(repository=self._repository)
        ids = await pipeline.execute(mem, force_new_conversation=force_new)
        await self._detect_conflicts(ids)
        return len(ids)

    async def _detect_conflicts(self, memory_ids: list[str]):
        try:
            from agentmind.memory.conflict_detector import MemoryConflictDetector
            detector = MemoryConflictDetector(self._repository)
            for memory_id in memory_ids:
                await detector.detect_for_memory(memory_id)
        except Exception as e:
            logger.debug("记忆冲突检测失败: %s", e)

    # ── 检索（暂用 store.search，阶段二完善）──

    async def search_memory(
        self,
        query: str = "",
        user_id: str = "",
        source_agent: str = "",
        tags: list[str] | None = None,
        access_levels: list[str] | None = None,
        exclude_conversation_id: str = "",
        limit: int = 10,
        attach_result_set: bool = True,
    ) -> list[dict]:
        card_results = await self._repository.search_cards(
            query=query,
            user_id=user_id,
            tags=tags or [],
            source_agent=source_agent,
            access_levels=access_levels or [],
            exclude_conversation_id=exclude_conversation_id,
            limit=limit,
        )
        dicts = []
        for row in card_results:
            dicts.append(self._card_row_to_search_dict(row))
        if dicts and attach_result_set:
            await self._attach_result_set_metadata(dicts, query, user_id)
        return dicts[:limit]

    @staticmethod
    def _card_row_to_search_dict(row: dict) -> dict:
        d = dict(row)
        card_text = d.get("card_text") or d.get("summary") or ""
        d["content"] = card_text
        d.setdefault("summary", card_text)
        d.setdefault("raw_memory_id", d.get("memory_id", ""))
        d["_route"] = "memory_cards"
        conflicts = (d.get("score_metadata") or {}).get("conflicts", [])
        if conflicts:
            d["_conflicts"] = conflicts
            d["_conflict_notice"] = "存在冲突记忆"
        return d

    async def _attach_result_set_metadata(
        self, rows: list[dict], query: str, user_id: str
    ):
        if not rows:
            return
        try:
            from agentmind.services.result_set_service import ResultSetService
            result_set_id = await ResultSetService(
                repository=self._repository
            ).create_result_set(
                user_id=user_id,
                query_text=query,
                memory_ids=[r["memory_id"] for r in rows],
                metadata={"route": "memory_cards"},
            )
        except Exception:
            return
        for index, row in enumerate(rows, start=1):
            row["_result_set_id"] = result_set_id
            row["_result_index"] = index

    async def search_memory_cards(
        self,
        query: str = "",
        user_id: str = "",
        source_agent: str = "",
        tags: list[str] | None = None,
        access_levels: list[str] | None = None,
        memory_types: list[MemoryType] | None = None,
        conversation_id: str = "",
        time_range_start: str = "",
        time_range_end: str = "",
        exclude_conversation_id: str = "",
        limit: int = 10,
    ) -> list[dict]:
        memory_type_values = [
            mt.value if hasattr(mt, "value") else str(mt)
            for mt in (memory_types or [])
        ]
        results = await self._repository.search_cards(
            query=query,
            user_id=user_id,
            tags=tags or [],
            source_agent=source_agent,
            access_levels=access_levels or [],
            memory_types=memory_type_values,
            conversation_id=conversation_id,
            exclude_conversation_id=exclude_conversation_id,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
            limit=limit,
        )
        return results[:limit]

    async def search_archive_memory(
        self,
        query: str = "",
        user_id: str = "",
        memory_types: list[MemoryType] | None = None,
        time_range_start: str = "",
        time_range_end: str = "",
        limit: int = 10,
    ) -> list[dict]:
        return await self._repository.search_archive(
            query=query,
            user_id=user_id,
            memory_types=memory_types or [],
            time_range_start=time_range_start,
            time_range_end=time_range_end,
            limit=limit,
        )

    async def expand_result(
        self,
        result_index: int,
        user_id: str,
        result_set_id: str = "",
    ) -> dict | None:
        from agentmind.services.result_set_service import ResultSetService
        svc = ResultSetService(repository=self._repository)
        target_result_set_id = result_set_id or await svc.get_latest_result_set_id(user_id)
        if not target_result_set_id:
            return None
        expanded = await svc.expand_result(target_result_set_id, result_index, user_id=user_id)
        if expanded is not None:
            expanded["_route"] = "result_set_expand"
        return expanded

    async def more_results(
        self,
        user_id: str,
        result_set_id: str = "",
        page_size: int = 5,
    ) -> dict | None:
        from agentmind.services.result_set_service import ResultSetService
        svc = ResultSetService(repository=self._repository)
        target_result_set_id = result_set_id or await svc.get_latest_result_set_id(user_id)
        if not target_result_set_id:
            return None
        page = await svc.next_page(target_result_set_id, user_id=user_id, page_size=page_size)
        if page is not None:
            page["_route"] = "result_set_more"
        return page

    # ── 统计 & 清理 ──

    async def get_memory_stats(self) -> dict:
        return await self._repository.get_stats()

    async def cleanup_memory(self, retention_days: int = 30) -> int:
        """清理过期记忆，返回删除数。"""
        deleted = await self._repository.cleanup_memory(retention_days=retention_days)
        if deleted:
            logger.info("清理记忆：%d 条", deleted)
        return deleted

    async def delete_memory(self, memory_id: str) -> bool:
        return await self._repository.delete(memory_id)

    # ── 会话管理 ──

    async def new_session(self, user_id: str) -> str:
        """用户发起 /new 时调用。关闭旧会话，开启新会话，清空 Working Memory。"""
        new_session_id = await self._repository.new_session(user_id)
        logger.info("新会话: user=%s session=%s", user_id[:12] if user_id else "-", new_session_id)
        return new_session_id

    def get_active_session(self, user_id: str) -> str | None:
        return self._repository.get_active_session_sync(user_id)

    def get_active_conversation_id(self, user_id: str) -> str | None:
        return self._repository.get_active_conversation_id_sync(user_id) or None

    def _clear_working_memory(self, user_id: str):
        """清空用户的 Working Memory（内存 LRU 缓存）。"""
        self._repository.clear_working_memory_sync(user_id)

    # ── Working Memory ──

    def add_to_working_memory(self, user_id: str, role: str, content: str):
        """记录一轮对话到 Working Memory（每轮 user + assistant）。"""
        self._repository.append_working_memory_sync(user_id, role, content)

    def get_working_memory(self, user_id: str, limit: int = 3) -> list[dict]:
        """获取最近 N 轮 Working Memory（每轮 = user + assistant 一对）。"""
        return self._repository.get_working_memory_sync(user_id, limit=limit)

    # ── 结构化问答轮次 ──

    async def read_conversation_turns(
        self,
        *,
        user_id: str,
        conversation_id: str = "",
        time_range_start: str = "",
        time_range_end: str = "",
        limit: int = 50,
    ) -> list[dict]:
        return await self._repository.read_conversation_turns(
            user_id=user_id,
            conversation_id=conversation_id,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
            limit=limit,
        )

    # ── 检索上下文 ──

    async def retrieve(
        self, message: str, user_id: str = "", settings: dict | None = None
    ) -> dict:
        """Compatibility dict wrapper around retrieve_context()."""
        ctx = await self.retrieve_context(message, user_id=user_id, settings=settings)
        return {
            "assembled_context": ctx.assembled_context,
            "recall_items": ctx.recall_items,
            "working_memory": ctx.working_memory,
            "result_set_id": ctx.result_set_id,
            "steps": ctx.steps,
            "truncated": ctx.truncated,
        }

    async def retrieve_context(
        self,
        message: str,
        user_id: str = "",
        settings: dict | None = None,
        limit: int = 5,
    ) -> MemoryContext:
        if settings is None:
            try:
                settings = ConfigService().read_settings()
            except Exception:
                settings = {}
        mem_cfg = settings.get("memory", {})
        steps = []

        try:
            from agentmind.memory.pipeline.query_understanding import (
                parse_conversation_history_query,
            )
            from agentmind.services.time_service import get_display_timezone

            history_query = parse_conversation_history_query(
                message,
                timezone_name=get_display_timezone(settings),
            )
        except Exception:
            history_query = None
        if history_query is not None:
            return await self._retrieve_conversation_history_context(
                message,
                user_id=user_id,
                settings=settings,
                history_query=history_query,
            )

        core_text = ""
        if user_id:
            try:
                core_text = await self._repository.read_core_memory(user_id)
                if core_text:
                    steps.append("core_memory")
            except Exception:
                core_text = ""

        working = []
        if user_id:
            working = self.get_working_memory(
                user_id, limit=mem_cfg.get("working_memory_rounds", 3)
            )
            if working:
                steps.append("working_memory")

        max_candidates = max(limit, mem_cfg.get("retrieval_max_candidates", limit))
        exclude_conversation_id = self.get_active_conversation_id(user_id) if working else ""
        knowledge_rows = await self._search_knowledge_rows(
            message,
            user_id=user_id,
            limit=max_candidates,
        )
        keyword_rows = await self.search_memory(
            query=message,
            user_id=user_id,
            access_levels=["shared"],
            exclude_conversation_id=exclude_conversation_id,
            limit=max_candidates,
            attach_result_set=False,
        )
        recent_rows = await self._repository.get_recent_cards(
            user_id=user_id,
            access_levels=["shared"],
            exclude_conversation_id=exclude_conversation_id,
            limit=max_candidates,
        )
        recent_rows = [self._card_row_to_search_dict(row) for row in recent_rows]
        relation_rows = await self._repository.related_cards_for_query(
            query=message,
            user_id=user_id,
            limit=max_candidates,
        )
        relation_rows = [self._card_row_to_search_dict(row) for row in relation_rows]
        vector_rows = await self._search_vector_rows(
            message,
            user_id=user_id,
            access_levels=["shared"],
            exclude_conversation_id=exclude_conversation_id,
            limit=max_candidates,
            settings=settings,
        )
        if knowledge_rows:
            steps.append("knowledge_items")
        if keyword_rows:
            steps.append("keyword_cards")
        if vector_rows:
            steps.append("vector_cards")
        if recent_rows:
            steps.append("recent_cards")
        if relation_rows:
            steps.append("relation_cards")
        rows = self._merge_retrieval_rows(
            keyword_rows,
            vector_rows,
            relation_rows,
            recent_rows,
        )
        rows = self._dedupe_memory_rows(rows)
        rows = self._rank_retrieval_rows(rows)
        rows, reranked = await self._rerank_rows(message, rows, mem_cfg)
        if reranked:
            steps.append("reranker")
        if rows:
            await self._attach_result_set_metadata(rows, message, user_id)
        if rows:
            steps.append("memory_cards")

        expanded_rows = []
        for row in rows[:3]:
            expanded = dict(row)
            raw_memory_id = expanded.get("raw_memory_id") or expanded.get("memory_id", "")
            try:
                raw = await self._repository.get_raw(raw_memory_id, user_id=user_id)
            except Exception:
                raw = None
            if raw and raw.get("content"):
                expanded["content"] = raw["content"]
            expanded_rows.append(expanded)
        expanded_rows.extend(rows[3:])

        recall_results = [self._dict_to_search_result(row) for row in expanded_rows]
        assembled_context = ""
        truncated = False
        try:
            from agentmind.memory.pipeline.assembler import ContextAssembler

            assembled = ContextAssembler().assemble(
                core_text,
                working,
                recall_results,
                knowledge_items=knowledge_rows,
                max_bytes=mem_cfg.get("context_max_bytes", 8192),
            )
            assembled_context = assembled.full_text
            truncated = assembled.truncated
            steps.append("context_assembler")
        except Exception as exc:
            logger.debug("Context assemble failed: %s", exc)

        result_set_id = rows[0].get("_result_set_id", "") if rows else ""
        return MemoryContext(
            assembled_context=assembled_context,
            working_memory=working,
            recall_items=expanded_rows[:limit],
            result_set_id=result_set_id,
            steps=steps,
            truncated=truncated,
        )

    async def _retrieve_conversation_history_context(
        self,
        message: str,
        user_id: str,
        settings: dict,
        history_query,
    ) -> MemoryContext:
        conversation_id = ""
        working = []
        if history_query.current_session:
            conversation_id = self.get_active_conversation_id(user_id) or ""
            working = self.get_working_memory(
                user_id,
                limit=settings.get("memory", {}).get("working_memory_rounds", 10),
            )
            if not conversation_id and not working:
                return MemoryContext(
                    assembled_context="",
                    working_memory=[],
                    recall_items=[],
                    steps=["conversation_history"],
                )

        rows = []
        if not history_query.current_session or conversation_id:
            rows = await self._repository.search_cards(
                query="",
                user_id=user_id,
                access_levels=["shared"],
                source_kinds=["conversation_turn", "task"],
                conversation_id=conversation_id,
                time_range_start=history_query.time_range_start,
                time_range_end=history_query.time_range_end,
                limit=history_query.limit,
            )
        rows = [self._card_row_to_search_dict(row) for row in rows]
        rows = self._dedupe_memory_rows(rows)
        rows = self._rank_retrieval_rows(rows)
        if rows:
            await self._attach_result_set_metadata(rows, message, user_id)

        assembled_context = ""
        truncated = False
        steps = ["conversation_history"]
        if rows:
            steps.append("memory_cards")
        try:
            from agentmind.memory.pipeline.assembler import ContextAssembler

            core_text = await self._repository.read_core_memory(user_id) if user_id else ""
            recall = [self._dict_to_search_result(row) for row in rows]
            assembled = ContextAssembler().assemble(
                core_text,
                working,
                recall,
                max_bytes=settings.get("memory", {}).get("context_max_bytes", 8192),
            )
            assembled_context = assembled.full_text
            truncated = assembled.truncated
            if assembled_context:
                steps.append("context_assembler")
        except Exception:
            pass

        return MemoryContext(
            assembled_context=assembled_context,
            working_memory=working,
            recall_items=rows[:history_query.limit],
            result_set_id=rows[0].get("_result_set_id", "") if rows else "",
            steps=steps,
            truncated=truncated,
        )

    async def _search_knowledge_rows(
        self,
        message: str,
        *,
        user_id: str,
        limit: int,
    ) -> list[dict]:
        if not hasattr(self._repository, "search_knowledge"):
            return []
        try:
            return await self._repository.search_knowledge(
                query=message,
                user_id=user_id,
                statuses=["active"],
                limit=limit,
            )
        except Exception as exc:
            logger.debug("Knowledge retrieval failed: %s", exc)
            return []

    async def _search_vector_rows(
        self,
        message: str,
        *,
        user_id: str,
        access_levels: list[str],
        exclude_conversation_id: str,
        limit: int,
        settings: dict,
    ) -> list[dict]:
        if not hasattr(self._repository, "search_vector"):
            return []
        if settings.get("embedding", {}).get("enabled") is False:
            return []
        try:
            query_embedding = await MemoryEmbeddingProvider().generate_embedding(message)
            if not query_embedding:
                return []
            rows = await self._repository.search_vector(
                query_embedding=query_embedding,
                user_id=user_id,
                access_levels=access_levels,
                exclude_conversation_id=exclude_conversation_id,
                limit=limit,
            )
            return [self._card_row_to_search_dict(row) for row in rows]
        except Exception as exc:
            logger.debug("Vector retrieval failed: %s", exc)
            return []

    @staticmethod
    def _dedupe_memory_rows(rows: list[dict]) -> list[dict]:
        seen = set()
        deduped = []
        for row in rows:
            memory_id = row.get("memory_id") or row.get("raw_memory_id")
            if memory_id in seen:
                continue
            seen.add(memory_id)
            deduped.append(row)
        return deduped

    @staticmethod
    def _rank_retrieval_rows(rows: list[dict]) -> list[dict]:
        def sort_key(row: dict):
            try:
                score = float(row.get("_score") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            return (
                -score,
                MemoryService._created_at_desc_sort_value(row.get("created_at", "")),
                row.get("memory_id", ""),
            )

        return sorted(rows, key=sort_key)

    @staticmethod
    def _created_at_desc_sort_value(created_at: str) -> int:
        digits = "".join(ch for ch in str(created_at or "") if ch.isdigit())[:14]
        if not digits:
            return 0
        return -int(digits.ljust(14, "0"))

    async def _rerank_rows(
        self, message: str, rows: list[dict], mem_cfg: dict
    ) -> tuple[list[dict], bool]:
        if not mem_cfg.get("reranker_enabled", False) or len(rows) <= 1:
            return rows, False
        try:
            from agentmind.memory.pipeline.reranker import Reranker

            candidates = [self._dict_to_search_result(row) for row in rows]
            reranked = await Reranker().rerank(message, candidates, top_k=len(rows))
        except Exception as exc:
            logger.debug("Reranker failed: %s", exc)
            return rows, False
        by_id = {row.get("memory_id"): row for row in rows}
        ordered = []
        seen = set()
        for item in reranked:
            memory_id = item.entry.memory_id
            row = by_id.get(memory_id)
            if row is None or memory_id in seen:
                continue
            row["_score"] = item.score
            ordered.append(row)
            seen.add(memory_id)
        ordered.extend(
            row for row in rows
            if row.get("memory_id") not in seen
        )
        return ordered, bool(ordered)

    @staticmethod
    def _merge_retrieval_rows(*row_groups: list[dict]) -> list[dict]:
        merged = []
        seen = set()
        for rows in row_groups:
            for row in rows:
                memory_id = row.get("memory_id") or row.get("raw_memory_id")
                if memory_id in seen:
                    continue
                seen.add(memory_id)
                merged.append(row)
        return merged

    @staticmethod
    def _dict_to_search_result(row: dict):
        from agentmind.memory.types import SearchResult

        entry = MemoryEntry.from_dict(row)
        return SearchResult(
            entry=entry,
            score=float(row.get("_score") or 0.0),
            route=row.get("_route", ""),
        )

    @property
    def store(self):
        return self._repository
