"""MemoryService — v4 记忆引擎统一入口"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from agentmind.memory.types import MemoryEntry, MemoryType, SearchQuery

logger = logging.getLogger("agentmind")


class MemoryService:
    """v4 记忆引擎服务单例。封装写入/检索/统计/清理/会话管理。"""

    _active_sessions: dict[str, str] = {}  # user_id -> current_session_id
    _force_new_next: dict[str, bool] = {}  # user_id -> 下次写入是否强制新建 conversation
    _working_memory: dict[str, list[dict]] = {}  # user_id -> [{role, content, ts}]
    _working_memory_max: int = 20  # 每个用户最多保留 20 条消息（10 轮）

    def __init__(self, store=None):
        if store is None:
            from agentmind.memory.sqlite_store import SqliteMemoryStore
            store = SqliteMemoryStore()
        self._store = store

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
            if self._force_new_next.pop(mem.user_id, False):
                force_new = True
            elif mem.memory_type == MemoryType.EPISODIC:
                current_sid = self._active_sessions.get(mem.user_id)
                if not current_sid:
                    force_new = True
                    self._active_sessions[mem.user_id] = f"sess-{uuid.uuid4().hex[:8]}"

        pipeline = WritePipeline(self._store)
        ids = await pipeline.execute(mem, force_new_conversation=force_new)
        return len(ids)

    # ── 检索（暂用 store.search，阶段二完善）──

    async def search_memory(
        self,
        query: str = "",
        user_id: str = "",
        source_agent: str = "",
        tags: list[str] | None = None,
        access_levels: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict]:
        search_query = SearchQuery(
            query_text=query,
            user_id=user_id,
            access_levels=access_levels or [],
            tags=tags or [],
            limit=limit,
        )
        results = await self._store.search(search_query)

        # 兼容旧 API 返回 dict 列表
        dicts = []
        for r in results:
            d = r.to_dict()
            if source_agent:
                if d.get("source_agent") != source_agent:
                    continue
            dicts.append(d)
        return dicts[:limit]

    # ── 统计 & 清理 ──

    async def get_memory_stats(self) -> dict:
        return await self._store.get_stats()

    async def cleanup_memory(self, retention_days: int = 30) -> int:
        """清理过期记忆，返回删除数。"""
        return await asyncio.to_thread(self._cleanup_sync, retention_days)

    def _cleanup_sync(self, retention_days: int) -> int:
        conn = self._store._get_conn()
        try:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            rows = conn.execute(
                "SELECT memory_id FROM memory_entries WHERE created_at <= datetime(?, ?)",
                (now, f"-{retention_days} days"),
            ).fetchall()
            if not rows:
                return 0

            ids = [r["memory_id"] for r in rows]
            for mid in ids:
                conn.execute("DELETE FROM memory_entries WHERE memory_id=?", (mid,))
                try:
                    conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (mid,))
                except Exception:
                    pass
                try:
                    from agentmind.storage.db import is_vec_available as _vec_ok
                    if _vec_ok():
                        conn.execute("DELETE FROM vec_memory WHERE memory_id=?", (mid,))
                except Exception:
                    pass
            conn.commit()
            logger.info("清理记忆：%d 条", len(ids))
            return len(ids)
        finally:
            conn.close()

    # ── 会话管理 ──

    async def new_session(self, user_id: str) -> str:
        """用户发起 /new 时调用。关闭旧会话，开启新会话，清空 Working Memory。"""
        if not user_id:
            return ""

        old_session_id = self._active_sessions.get(user_id)

        # 关闭旧 conversation
        if old_session_id:
            try:
                from agentmind.memory.components.conversation_merger import ConversationMerger
                conn = self._store._get_conn()
                try:
                    # 找到最近的活跃 conversation 并关闭
                    row = conn.execute(
                        """SELECT conversation_id FROM conversations
                           WHERE user_id=? AND status='active'
                           ORDER BY last_message_at DESC LIMIT 1""",
                        (user_id,),
                    ).fetchone()
                    if row:
                        merger = ConversationMerger()
                        merger.close_conversation(conn, row["conversation_id"])
                    conn.commit()
                finally:
                    conn.close()
            except Exception as e:
                logger.debug("关闭旧 conversation 失败: %s", e)

        # 生成新 session_id
        new_session_id = f"sess-{uuid.uuid4().hex[:8]}"
        self._active_sessions[user_id] = new_session_id
        self._force_new_next[user_id] = True  # 下次写入强制新 conversation

        # 清空 Working Memory（阶段二检索时用到，这里提前占位）
        self._clear_working_memory(user_id)

        logger.info("新会话: user=%s session=%s", user_id[:12] if user_id else "-", new_session_id)
        return new_session_id

    def get_active_session(self, user_id: str) -> str | None:
        return self._active_sessions.get(user_id)

    def _clear_working_memory(self, user_id: str):
        """清空用户的 Working Memory（内存 LRU 缓存）。"""
        self._working_memory.pop(user_id, None)

    # ── Working Memory ──

    def add_to_working_memory(self, user_id: str, role: str, content: str):
        """记录一轮对话到 Working Memory（每轮 user + assistant）。"""
        if not user_id or not content:
            return
        if user_id not in self._working_memory:
            self._working_memory[user_id] = []
        entry = {
            "role": role,
            "content": (content or "")[:500],
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._working_memory[user_id].append(entry)
        if len(self._working_memory[user_id]) > self._working_memory_max:
            self._working_memory[user_id] = self._working_memory[user_id][-self._working_memory_max:]

    def get_working_memory(self, user_id: str, limit: int = 3) -> list[dict]:
        """获取最近 N 轮 Working Memory（每轮 = user + assistant 一对）。"""
        entries = self._working_memory.get(user_id, [])
        if not entries:
            return []
        rounds = []
        i = 0
        while i < len(entries):
            e = entries[i]
            if e["role"] == "user":
                nxt = entries[i + 1] if i + 1 < len(entries) else None
                assistant = nxt["content"] if nxt and nxt["role"] == "assistant" else ""
                rounds.append({"user": e["content"], "assistant": assistant, "ts": e["ts"]})
                i += 2 if (nxt and nxt["role"] == "assistant") else 1
            else:
                i += 1
        return rounds[-limit:] if len(rounds) > limit else rounds

    # ── v4 检索流水线 ──

    async def retrieve(
        self, message: str, user_id: str = "", settings: dict | None = None
    ) -> dict:
        """v4 7-step 检索流水线。返回 dict 含 assembled_context / recall_items / steps。"""
        if settings is None:
            try:
                from agentmind.storage.memory import _load_settings
                settings = _load_settings()
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
        return self._store
