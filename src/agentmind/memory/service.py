"""MemoryService — v4 记忆引擎统一入口"""

import asyncio
import logging

from agentmind.memory.types import MemoryEntry, MemoryType, SearchQuery
from agentmind.services.config_service import ConfigService
from agentmind.services.session_service import SessionService

logger = logging.getLogger("agentmind")


class MemoryService:
    """v4 记忆引擎服务单例。封装写入/检索/统计/清理/会话管理。"""

    def __init__(self, store=None, repository=None):
        if store is None:
            from agentmind.memory.sqlite_store import SqliteMemoryStore
            store = SqliteMemoryStore()
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
            session = SessionService(self._store)
            if session.consume_force_new(mem.user_id):
                force_new = True
            elif mem.memory_type == MemoryType.EPISODIC:
                _, created = session.ensure_active_session(mem.user_id)
                force_new = created

        pipeline = WritePipeline(self._store)
        ids = await pipeline.execute(mem, force_new_conversation=force_new)
        await self._detect_conflicts(ids)
        return len(ids)

    async def _detect_conflicts(self, memory_ids: list[str]):
        try:
            from agentmind.memory.conflict_detector import MemoryConflictDetector
            detector = MemoryConflictDetector(self._store)
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
        search_query = SearchQuery(
            query_text=query,
            user_id=user_id,
            access_levels=access_levels or [],
            tags=tags or [],
            exclude_conversation_id=exclude_conversation_id,
            limit=limit,
        )
        card_results = await self._store.search_memory_cards(search_query)
        dicts = []
        for row in card_results:
            if source_agent and row.get("source_agent") != source_agent:
                continue
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
        search_query = SearchQuery(
            query_text=query,
            user_id=user_id,
            memory_types=memory_types or [],
            access_levels=access_levels or [],
            tags=tags or [],
            conversation_id=conversation_id,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
            exclude_conversation_id=exclude_conversation_id,
            limit=limit,
        )
        results = await self._store.search_memory_cards(search_query)

        dicts = []
        for row in results:
            if source_agent and row.get("source_agent") != source_agent:
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
        search_query = SearchQuery(
            query_text=query,
            user_id=user_id,
            memory_types=memory_types or [],
            time_range_start=time_range_start,
            time_range_end=time_range_end,
            limit=limit,
        )
        return await self._store.search_archive_memory(search_query)

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
        return await self._store.get_stats()

    async def cleanup_memory(self, retention_days: int = 30) -> int:
        """清理过期记忆，返回删除数。"""
        deleted = await self._store.cleanup_memory(retention_days=retention_days)
        if deleted:
            logger.info("清理记忆：%d 条", deleted)
        return deleted

    async def delete_memory(self, memory_id: str) -> bool:
        return await self._store.delete(memory_id)

    # ── 会话管理 ──

    async def new_session(self, user_id: str) -> str:
        """用户发起 /new 时调用。关闭旧会话，开启新会话，清空 Working Memory。"""
        new_session_id = await SessionService(self._store).new_session(user_id)
        logger.info("新会话: user=%s session=%s", user_id[:12] if user_id else "-", new_session_id)
        return new_session_id

    def get_active_session(self, user_id: str) -> str | None:
        return SessionService(self._store).get_active_session(user_id)

    def get_active_conversation_id(self, user_id: str) -> str | None:
        try:
            return self._repository.get_active_conversation_id_sync(user_id) or None
        except Exception:
            return SessionService(self._store).get_active_conversation_id(user_id)

    def _clear_working_memory(self, user_id: str):
        """清空用户的 Working Memory（内存 LRU 缓存）。"""
        SessionService(self._store).clear_working_memory(user_id)

    # ── Working Memory ──

    def add_to_working_memory(self, user_id: str, role: str, content: str):
        """记录一轮对话到 Working Memory（每轮 user + assistant）。"""
        SessionService(self._store).add_to_working_memory(user_id, role, content)

    def get_working_memory(self, user_id: str, limit: int = 3) -> list[dict]:
        """获取最近 N 轮 Working Memory（每轮 = user + assistant 一对）。"""
        return SessionService(self._store).get_working_memory(user_id, limit=limit)

    # ── v4 检索流水线 ──

    async def retrieve(
        self, message: str, user_id: str = "", settings: dict | None = None
    ) -> dict:
        """v4 7-step 检索流水线。返回 dict 含 assembled_context / recall_items / steps。"""
        if settings is None:
            try:
                settings = ConfigService().read_settings()
            except Exception:
                settings = {}

        mem_cfg = settings.get("memory", {})
        if not mem_cfg.get("v4_retrieval_enabled", False):
            return {"assembled_context": "", "recall_items": [], "steps": ["v4_disabled"]}

        from agentmind.memory.pipeline.recall import RetrievalPipeline

        pipeline = RetrievalPipeline(self._store, self)
        result = await pipeline.retrieve(message, user_id, settings)

        return {
            "assembled_context": result.assembled_context,
            "recall_items": [r.to_dict() for r in result.recall_items],
            "core_memory": result.core_memory,
            "working_memory": result.working_memory,
            "rewritten_query": result.rewritten_query.expanded_query if result.rewritten_query else message,
            "steps": result.steps_executed,
            "truncated": result.truncated,
        }

    @property
    def store(self):
        # Migration-only compatibility for legacy callers; remove in Phase 9.
        return self._store
