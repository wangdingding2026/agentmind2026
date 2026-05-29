"""Embedding 迁移 Worker — 切换 embedding 模型时批量重建向量索引"""

import logging

from agentmind.memory.provider import (
    MemoryEmbeddingProvider,
    embedding_to_blob,
    read_memory_settings,
)

logger = logging.getLogger("agentmind")


async def run_embedding_migration(store) -> int:
    """
    检测到 embedding_version 变更时，批量重建新版本向量。
    当前实现为骨架：取旧版本记忆，用新模型重新 embedding，
    写入 vec_memory_v{N+1}，更新 embedding_version。
    返回迁移条数。
    """
    conn = store._get_conn()
    try:
        # 查找需要迁移的记忆（embedding_version < 当前目标版本）
        settings = read_memory_settings()
        emb_cfg = settings.get("embedding", {})
        target_version = emb_cfg.get("version", 1)

        if target_version <= 1:
            return 0  # 无需迁移

        rows = conn.execute(
            "SELECT memory_id, content, summary FROM memory_entries WHERE embedding_version < ? LIMIT 100",
            (target_version,),
        ).fetchall()

        if not rows:
            return 0

        # 确保新 vec 表存在
        dim = emb_cfg.get("dimension", 384)
        new_table = f"vec_memory_v{target_version}"
        try:
            conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {new_table} USING vec0(
                    memory_id TEXT PRIMARY KEY, embedding FLOAT[{dim}]
                )
            """)
        except Exception:
            logger.debug("无法创建 %s，跳过迁移", new_table)
            return 0

        migrated = 0
        for r in rows:
            mid = r["memory_id"]
            text = ((r["content"] or "") + " " + (r["summary"] or ""))[:8000]
            try:
                emb = await MemoryEmbeddingProvider().generate_embedding(text)
                if emb:
                    blob = embedding_to_blob(emb)
                    conn.execute(
                        f"INSERT OR REPLACE INTO {new_table}(memory_id, embedding) VALUES (?, ?)",
                        (mid, blob),
                    )
                    conn.execute(
                        "UPDATE memory_entries SET embedding_version=?, embedding_model=? WHERE memory_id=?",
                        (target_version, emb_cfg.get("model", ""), mid),
                    )
                    migrated += 1
            except Exception:
                pass

        conn.commit()
        logger.info("Embedding 迁移完成：%d 条 → %s", migrated, new_table)
        return migrated
    finally:
        conn.close()
