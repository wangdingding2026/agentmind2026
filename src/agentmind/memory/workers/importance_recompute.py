"""重要性衰减 Worker — 时间衰减 importance 值"""

import logging

logger = logging.getLogger("agentmind")


async def run_importance_recompute(store) -> int:
    """
    对所有 importance > 0 的记忆执行 importance *= 0.99（每日衰减 1%）。
    返回更新的行数。
    """
    conn = store._get_conn()
    try:
        result = conn.execute(
            "UPDATE memory_entries SET importance = ROUND(importance * 0.99, 4) WHERE importance > 0"
        )
        conn.commit()
        updated = result.rowcount
        if updated:
            logger.debug("重要性衰减：%d 条记忆 updated", updated)
        return updated
    finally:
        conn.close()
