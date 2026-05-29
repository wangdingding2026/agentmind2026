"""Archive worker for canonical raw/card memory."""

import logging

logger = logging.getLogger("agentmind")


async def run_archival(repository, worker_cfg: dict) -> int:
    """
    Archive old distilled raw/card memories through repository boundary.
    """
    retention_days = worker_cfg.get("archival_retention_days", 90)
    archived_count = await repository.archive_distilled_cards(retention_days=retention_days)
    logger.info("归档完成：%d 条", archived_count)
    return archived_count
