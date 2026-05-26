"""Core Memory 管理 — 检测候选 + 读写 core_memory 表"""

import json
import logging
from datetime import datetime, timezone

from agentmind.memory.types import MemoryEntry

logger = logging.getLogger("agentmind")

# 自述触发词
_SELF_DECLARATION_RE = __import__("re").compile(
    r'我是|我喜欢|我在做|我的项目|我常用|我偏好|我习惯|我的工作是'
)


class CoreMemoryManager:
    """管理 Core Memory：始终注入 system prompt 前缀的结构化用户画像。"""

    @staticmethod
    def is_candidate(entry: MemoryEntry) -> bool:
        """判断一条记忆是否应成为 Core Memory 候选。"""
        if entry.importance >= 0.7:
            return True
        content = f"{entry.content} {entry.summary}"
        if _SELF_DECLARATION_RE.search(content):
            return True
        return False

    @staticmethod
    def guess_slot(content: str, summary: str) -> str:
        """根据内容猜测应写入哪个 slot。"""
        text = f"{content} {summary}"
        if __import__("re").search(r'我是|我喜欢|我偏好|我习惯|我常用', text):
            return "preferences"
        if __import__("re").search(r'我的项目|我在做|我负责|我管理', text):
            return "current_projects"
        if __import__("re").search(r'我的工作是|我的角色|我的职责|我的职位', text):
            return "profile"
        return "pinned_facts"

    @staticmethod
    async def upsert(store, entry: MemoryEntry):
        """将候选写入 core_memory 表（状态 pending，需人工确认）。"""
        try:
            slot = CoreMemoryManager.guess_slot(entry.content, entry.summary)
            value = json.dumps({
                "content": entry.content[:500],
                "summary": entry.summary[:500],
                "source_memory_id": entry.memory_id,
                "importance": entry.importance,
            }, ensure_ascii=False)
            byte_size = len(value.encode("utf-8"))
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

            conn = store._get_conn()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO core_memory
                       (user_id, slot_key, slot_value, byte_size, updated_at, updated_by, status)
                       VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
                    (entry.user_id or "default", slot, value, byte_size, now, entry.source_agent),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.debug("CoreMemory upsert 失败: %s", e)

    @staticmethod
    async def confirm(store, user_id: str, slot_key: str) -> bool:
        """确认一条 pending core memory，使其生效。"""
        try:
            conn = store._get_conn()
            try:
                conn.execute(
                    "UPDATE core_memory SET status='confirmed' WHERE user_id=? AND slot_key=?",
                    (user_id or "default", slot_key),
                )
                conn.commit()
                return conn.total_changes > 0
            finally:
                conn.close()
        except Exception as e:
            logger.debug("CoreMemory confirm 失败: %s", e)
            return False

    @staticmethod
    async def list_pending(store, user_id: str) -> list[dict]:
        """列出所有待确认的 core memory 候选。"""
        try:
            conn = store._get_conn()
            try:
                rows = conn.execute(
                    "SELECT slot_key, slot_value, updated_at FROM core_memory WHERE user_id=? AND status='pending'",
                    (user_id or "default",),
                ).fetchall()
                results = []
                for r in rows:
                    results.append({
                        "slot_key": r["slot_key"],
                        "slot_value": r["slot_value"],
                        "updated_at": r["updated_at"],
                    })
                return results
            finally:
                conn.close()
        except Exception as e:
            logger.debug("CoreMemory list_pending 失败: %s", e)
            return []
