"""Embedding 迁移 Worker — 切换 embedding 模型时批量重建向量索引"""

import logging

from agentmind.memory.provider import (
    read_memory_settings,
)

logger = logging.getLogger("agentmind")


async def run_embedding_migration(repository) -> int:
    """
    Check vector compatibility through the canonical repository boundary.

    Phase 8 keeps vector support usable without making it a runtime primary
    retrieval path. Rebuild mechanics remain repository-owned.
    """
    settings = read_memory_settings()
    emb_cfg = settings.get("embedding", {})
    target_version = emb_cfg.get("version", 1)
    migrated = await repository.rebuild_vector_index(
        target_version=target_version,
        model=emb_cfg.get("model", ""),
        limit=100,
    )
    logger.info("Embedding 兼容检查完成：%d 条", migrated)
    return migrated
