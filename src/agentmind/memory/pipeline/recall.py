"""Legacy-compatible retrieval pipeline wrapper.

Canonical prompt retrieval is handled by MemoryService.retrieve_context().
This class remains for callers that still import RetrievalPipeline during
migration, but runtime storage reads must go through MemoryService/repository.
"""

import logging
from dataclasses import dataclass, field

from agentmind.memory.types import MemoryEntry, RewrittenQuery, SearchQuery, SearchResult

logger = logging.getLogger("agentmind")


@dataclass
class RetrievalResult:
    core_memory: str = ""
    working_memory: list[dict] = field(default_factory=list)
    recall_items: list[SearchResult] = field(default_factory=list)
    rewritten_query: RewrittenQuery = field(default_factory=RewrittenQuery)
    assembled_context: str = ""
    assembled_context_bytes: int = 0
    truncated: bool = False
    steps_executed: list[str] = field(default_factory=list)


class RetrievalPipeline:
    """7 步检索流水线。每步 try/except 兜底，任一步失败不影响后续。"""

    def __init__(self, store, memory_service: "MemoryService" = None):
        self._store = store
        self._service = memory_service
        self._repository = getattr(memory_service, "_repository", None)

    async def retrieve(
        self, message: str, user_id: str, settings: dict
    ) -> RetrievalResult:
        mem_cfg = settings.get("memory", {})
        steps = []

        # Step 1: Core Memory
        core_text = ""
        if self._repository:
            try:
                core_text = await self._repository.read_core_memory(user_id)
                if core_text:
                    steps.append("core_memory")
            except Exception as e:
                logger.debug("Core Memory 读取失败: %s", e)

        # Step 2: Working Memory
        working = []
        if self._service:
            try:
                limit = mem_cfg.get("working_memory_rounds", 3)
                working = self._service.get_working_memory(user_id, limit=limit)
                if working:
                    steps.append("working_memory")
            except Exception as e:
                logger.debug("Working Memory 读取失败: %s", e)

        # Step 3: Query Understanding
        rewritten = RewrittenQuery(expanded_query=message)
        try:
            from agentmind.memory.pipeline.query_understanding import QueryUnderstanding
            rewritten = await QueryUnderstanding.rewrite(message, user_id)
            if rewritten.confidence > 0.0:
                steps.append("query_understanding")
        except Exception as e:
            logger.debug("Query Understanding 失败: %s", e)

        # Step 4: Multi-Route Recall
        search_text = rewritten.expanded_query or message
        search_query = SearchQuery(
            query_text=search_text,
            user_id=user_id,
            access_levels=["shared"],
            limit=mem_cfg.get("retrieval_max_candidates", 30),
            time_range_start=rewritten.date_filter or "",
            time_range_end=rewritten.date_filter or "",
            exclude_conversation_id=self._active_conversation_id(user_id) if working else "",
            entities=rewritten.entity_filters,
        )
        recall = await self._recall(search_text, user_id, search_query)
        steps.append("multi_route_recall")

        # Step 5: Reranker (optional)
        if mem_cfg.get("reranker_enabled", False) and recall:
            try:
                from agentmind.memory.pipeline.reranker import Reranker
                reranker = Reranker()
                recall = await reranker.rerank(search_text, recall)
                steps.append("reranker")
            except Exception as e:
                logger.debug("Reranker 失败: %s", e)

        # Step 6: Post-filter (date hard filter if Query Understanding extracted date)
        if rewritten.date_filter:
            recall = self._apply_date_filter(recall, rewritten.date_filter)
            steps.append("post_filter")
        else:
            steps.append("post_filter")  # 无日期过滤也算执行了

        # Step 7: Context Assembler
        assembled_text = ""
        assembled_bytes = 0
        truncated = False
        try:
            from agentmind.memory.pipeline.assembler import ContextAssembler
            assembler = ContextAssembler()
            max_bytes = mem_cfg.get("context_max_bytes", 8192)
            result = assembler.assemble(core_text, working, recall, max_bytes=max_bytes)
            assembled_text = result.full_text
            assembled_bytes = result.total_bytes
            truncated = result.truncated
            steps.append("context_assembler")
        except Exception as e:
            logger.debug("Context Assembler 失败: %s", e)

        return RetrievalResult(
            core_memory=core_text,
            working_memory=working,
            recall_items=recall,
            rewritten_query=rewritten,
            assembled_context=assembled_text,
            assembled_context_bytes=assembled_bytes,
            truncated=truncated,
            steps_executed=steps,
        )

    async def _recall(
        self, search_text: str, user_id: str, search_query: SearchQuery
    ) -> list[SearchResult]:
        if self._service:
            rows = await self._service.search_memory(
                query=search_text,
                user_id=user_id,
                access_levels=search_query.access_levels,
                exclude_conversation_id=search_query.exclude_conversation_id,
                limit=search_query.limit,
            )
            return [self._dict_to_search_result(row) for row in rows]
        return []

    def _active_conversation_id(self, user_id: str) -> str:
        if not self._service:
            return ""
        try:
            return self._service.get_active_conversation_id(user_id) or ""
        except Exception:
            return ""

    @staticmethod
    def _dict_to_search_result(row: dict) -> SearchResult:
        entry = MemoryEntry.from_dict(row)
        return SearchResult(
            entry=entry,
            score=float(row.get("_score") or 0.0),
            route=row.get("_route", ""),
        )

    @staticmethod
    def _apply_date_filter(
        recall: list[SearchResult], date_str: str
    ) -> list[SearchResult]:
        if not date_str:
            return recall
        return [r for r in recall if (r.entry.created_at or "").startswith(date_str)]
