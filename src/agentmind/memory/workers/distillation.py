"""蒸馏 Worker — 将旧的、低重要性的 episodic 记忆聚合成 semantic 摘要"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger("agentmind")


async def run_distillation(store, worker_cfg: dict) -> int:
    """
    取 7-30 天前、importance < 0.4 的 episodic 记忆，
    按 conversation_id 聚合 → 生成简单摘要 → 写入 semantic，
    原条目标记 distilled=1。
    返回蒸馏的记忆数。
    """
    min_age = worker_cfg.get("distillation_min_age_days", 7)
    max_age = worker_cfg.get("distillation_max_age_days", 30)
    imp_threshold = worker_cfg.get("distillation_importance_threshold", 0.4)

    conn = store._get_conn()
    try:
        # 取符合条件的 episodic 记忆
        rows = conn.execute(
            """SELECT * FROM memory_entries
               WHERE memory_type='episodic'
                 AND distilled=0
                 AND importance < ?
                 AND created_at <= datetime('now', ? || ' days')
                 AND created_at >= datetime('now', ? || ' days')
               ORDER BY conversation_id, created_at""",
            (imp_threshold, f"-{min_age}", f"-{max_age}"),
        ).fetchall()

        if not rows:
            return 0

        # 按 conversation_id 分组
        groups: dict[str, list] = {}
        for r in rows:
            cid = r["conversation_id"] or "_no_conv"
            if cid not in groups:
                groups[cid] = []
            groups[cid].append(dict(r))

        distilled_count = 0
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        for cid, entries in groups.items():
            # 聚合摘要（简单拼接，不调 LLM）
            contents = [e["content"][:200] for e in entries[:20]]
            summaries = [e["summary"][:200] for e in entries[:20]]
            merged_content = "；".join(contents)
            merged_summary = " | ".join(summaries)
            user_id = entries[0].get("user_id", "")

            # 写入 semantic 记忆（通过 store.insert() 统一维护 FTS 索引）
            import uuid
            from agentmind.memory.types import MemoryEntry, MemoryType
            sem_id = f"distill-{uuid.uuid4().hex[:12]}"
            try:
                sem_entry = MemoryEntry(
                    memory_id=sem_id,
                    content=merged_content[:2000],
                    summary=merged_summary[:1000],
                    source_agent="distillation",
                    user_id=user_id,
                    memory_type=MemoryType.SEMANTIC,
                    conversation_id=cid,
                    importance=0.5,
                    created_at=now,
                    access_level="shared",
                )
                await store.insert(sem_entry)
            except Exception:
                pass

            # 标记原条目
            for e in entries:
                try:
                    conn.execute(
                        "UPDATE memory_entries SET distilled=1 WHERE memory_id=?",
                        (e["memory_id"],),
                    )
                    distilled_count += 1
                except Exception:
                    pass

        conn.commit()
        logger.info("蒸馏完成：%d 条 → %d 组 semantic", distilled_count, len(groups))
        return distilled_count
    finally:
        conn.close()
