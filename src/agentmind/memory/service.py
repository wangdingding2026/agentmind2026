"""MemoryService — canonical memory engine entry point."""

import logging

from agentmind.memory.dto import MemoryContext
from agentmind.memory.types import MemoryEntry, MemoryType
from agentmind.services.config_service import ConfigService

logger = logging.getLogger("agentmind")


class MemoryService:
    """Canonical memory service for write, retrieval, stats, cleanup, and sessions."""

    def __init__(self, store=None, repository=None):
        if store is None:
            from agentmind.memory.sqlite_store import SqliteMemoryStore
            store = SqliteMemoryStore(getattr(repository, "_db_path", ""))
        if repository is None:
            from agentmind.memory.repository_sqlite import SqliteMemoryRepository
            repository = SqliteMemoryRepository(getattr(store, "_db_path", ""))
        self._store = store
        self._repository = repository

    # ── 写入 ──

    async def write_memory(
        self, entry: dict, generate_embedding: bool = True, user_id: str = ""
    ) -> int:
        """写入记忆。兼容旧 write_memory() 签名。返回写入条数（chunking 可能产生多条）。"""
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

        pipeline = WritePipeline(self._store, repository=self._repository)
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
    ) -> list[dict]:
        card_results = await self._repository.search_cards(
            query=query,
            user_id=user_id,
            tags=tags or [],
            source_agent=source_agent,
            access_levels=access_levels or [],
            limit=limit,
        )
        if exclude_conversation_id:
            card_results = [
                row for row in card_results
                if row.get("conversation_id") != exclude_conversation_id
                and row.get("session_id") != exclude_conversation_id
            ]
        dicts = []
        for row in card_results:
            dicts.append(self._card_row_to_search_dict(row))
        if dicts:
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
                self._store, repository=self._repository
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
        results = await self._repository.search_cards(
            query=query,
            user_id=user_id,
            tags=tags or [],
            source_agent=source_agent,
            access_levels=access_levels or [],
            limit=limit * 3,
        )
        dicts = []
        for row in results:
            if memory_types and row.get("memory_type") not in {mt.value for mt in memory_types}:
                continue
            if conversation_id and row.get("conversation_id") != conversation_id and row.get("session_id") != conversation_id:
                continue
            if exclude_conversation_id and (
                row.get("conversation_id") == exclude_conversation_id
                or row.get("session_id") == exclude_conversation_id
            ):
                continue
            created_at = row.get("created_at") or ""
            if time_range_start and created_at < time_range_start:
                continue
            if time_range_end and created_at > time_range_end:
                continue
            dicts.append(row)
        return dicts[:limit]

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
        svc = ResultSetService(self._store, repository=self._repository)
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
        svc = ResultSetService(self._store, repository=self._repository)
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

    # ── v4 检索流水线 ──

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
        keyword_rows = await self.search_memory(
            query=message,
            user_id=user_id,
            access_levels=["shared"],
            exclude_conversation_id=exclude_conversation_id,
            limit=max_candidates,
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
        if keyword_rows:
            steps.append("keyword_cards")
        if recent_rows:
            steps.append("recent_cards")
        if relation_rows:
            steps.append("relation_cards")
        rows = self._merge_retrieval_rows(keyword_rows, relation_rows, recent_rows)
        rows = self._dedupe_memory_rows(rows)
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
        # Migration-only compatibility for legacy callers; remove in Phase 9.
        return self._store
