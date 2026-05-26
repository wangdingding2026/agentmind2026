"""对话归并 — 将同用户短时间内连续的 episodic 记忆归入同一 conversation"""

import logging
import sqlite3
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("agentmind")


class ConversationMerger:
    """将 episodic 记忆归并到 conversation 容器。"""

    def __init__(self, window_minutes: int = 30):
        self.window_minutes = window_minutes

    def find_or_create(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        content: str,
        window_minutes: int | None = None,
        force_new: bool = False,
    ) -> str:
        """查找活跃 conversation 或创建新的。返回 conversation_id。"""
        if not user_id:
            return ""

        window = window_minutes if window_minutes is not None else self.window_minutes

        if not force_new:
            conv_id = self._find_active(conn, user_id, window)
            if conv_id:
                self._touch(conn, conv_id)
                return conv_id

        return self._create(conn, user_id)

    def close_conversation(self, conn: sqlite3.Connection, conversation_id: str):
        """关闭一个 conversation（用户主动 /new 时调用）"""
        if not conversation_id:
            return
        try:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE conversations SET status='closed', last_message_at=? WHERE conversation_id=?",
                (now, conversation_id),
            )
        except Exception:
            pass

    def _find_active(self, conn, user_id: str, window_minutes: int) -> str | None:
        try:
            row = conn.execute(
                """SELECT conversation_id FROM conversations
                   WHERE user_id=? AND status='active'
                     AND last_message_at >= datetime('now', ? || ' minutes')
                   ORDER BY last_message_at DESC LIMIT 1""",
                (user_id, f"-{window_minutes}"),
            ).fetchone()
            return row["conversation_id"] if row else None
        except Exception as e:
            logger.debug("ConversationMerger 查询失败: %s", e)
            return None

    def _create(self, conn, user_id: str) -> str:
        conv_id = f"conv-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        try:
            conn.execute(
                """INSERT OR IGNORE INTO conversations
                   (conversation_id, user_id, first_message_at, last_message_at, status)
                   VALUES (?, ?, ?, ?, 'active')""",
                (conv_id, user_id, now, now),
            )
        except Exception:
            pass
        return conv_id

    def _touch(self, conn, conv_id: str):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        try:
            conn.execute(
                "UPDATE conversations SET last_message_at=?, message_count=message_count+1 WHERE conversation_id=?",
                (now, conv_id),
            )
        except Exception:
            pass
