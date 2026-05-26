"""Worker 调度器 — 管理 4 个后台 worker 的启停，asyncio 原生实现"""

import asyncio
import logging

logger = logging.getLogger("agentmind")


class MemoryWorkerScheduler:
    """管理蒸馏/归档/衰减/迁移 4 个 worker 的生命周期。"""

    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False

    async def start(self, settings: dict):
        """按 config 启动已启用的 worker。返回启动的 worker 数量。"""
        mem_cfg = settings.get("memory", {})
        worker_cfg = mem_cfg.get("workers", {})
        if not worker_cfg.get("enabled", False):
            logger.debug("Memory workers 未启用（memory.workers.enabled=false）")
            return 0

        store = self._get_store()

        # Distillation
        if worker_cfg.get("distillation_enabled", False):
            interval = worker_cfg.get("distillation_interval_hours", 24)
            self._tasks["distillation"] = asyncio.create_task(
                self._run_periodic("distillation", store, worker_cfg, interval)
            )

        # Archival
        if worker_cfg.get("archival_enabled", False):
            interval = worker_cfg.get("archival_interval_hours", 168)  # 7 days
            self._tasks["archival"] = asyncio.create_task(
                self._run_periodic("archival", store, worker_cfg, interval)
            )

        # Importance recompute
        if worker_cfg.get("importance_recompute_enabled", False):
            interval = worker_cfg.get("importance_recompute_interval_hours", 24)
            self._tasks["importance"] = asyncio.create_task(
                self._run_periodic("importance", store, worker_cfg, interval)
            )

        # Embedding migration
        emb_cfg = settings.get("embedding", {})
        if emb_cfg.get("migration", {}).get("enabled", False):
            interval = emb_cfg["migration"].get("interval_hours", 24)
            self._tasks["embedding"] = asyncio.create_task(
                self._run_periodic("embedding", store, worker_cfg, interval)
            )

        self._running = True
        logger.info("Memory workers 已启动: %s", list(self._tasks.keys()))
        return len(self._tasks)

    async def stop(self):
        """停止所有 worker。"""
        self._running = False
        for name, task in self._tasks.items():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
            logger.info("Memory workers 已停止: %s", list(self._tasks.keys()))
        self._tasks.clear()

    async def _run_periodic(
        self, name: str, store, worker_cfg: dict, interval_hours: int
    ):
        """定时循环运行 worker，首次延迟 60s 避免启动风暴。"""
        interval_secs = max(60, interval_hours * 3600)
        # 首次运行延迟
        first_delay = min(60, interval_secs)
        await asyncio.sleep(first_delay)

        while self._running:
            try:
                if name == "distillation":
                    from agentmind.memory.workers.distillation import run_distillation
                    await run_distillation(store, worker_cfg)
                elif name == "archival":
                    from agentmind.memory.workers.archival import run_archival
                    await run_archival(store, worker_cfg)
                elif name == "importance":
                    from agentmind.memory.workers.importance_recompute import run_importance_recompute
                    await run_importance_recompute(store)
                elif name == "embedding":
                    from agentmind.memory.workers.embedding_migration import run_embedding_migration
                    await run_embedding_migration(store)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Worker %s 执行失败: %s", name, e)

            try:
                await asyncio.sleep(interval_secs)
            except asyncio.CancelledError:
                break

    @staticmethod
    def _get_store():
        from agentmind.memory.sqlite_store import SqliteMemoryStore
        return SqliteMemoryStore()
