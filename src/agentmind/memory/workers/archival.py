"""归档 Worker — 将 90 天前已蒸馏的记忆压缩迁移到 archive.db"""

import gzip
import logging
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger("agentmind")


async def run_archival(store, worker_cfg: dict) -> int:
    """
    取 90 天前且 distilled=1 的记忆 → gzip 压缩 content →
    写入 archive_YYYY_MM 表 → 主库删除。返回归档条数。
    """
    retention_days = worker_cfg.get("archival_retention_days", 90)

    conn = store._get_conn()
    archive_path = store._db_path.replace("memory.db", "archive.db")

    try:
        rows = conn.execute(
            """SELECT * FROM memory_entries
               WHERE distilled=1
                 AND created_at <= datetime('now', ? || ' days')
               LIMIT 1000""",
            (f"-{retention_days}",),
        ).fetchall()

        if not rows:
            return 0

        archive_conn = sqlite3.connect(archive_path, timeout=10)
        archived_count = 0
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        memory_ids = []

        try:
            for r in rows:
                d = dict(r)
                memory_ids.append(d["memory_id"])

                # 按月分表
                created = d.get("created_at", now)
                try:
                    dt = datetime.strptime(created[:10], "%Y-%m-%d")
                    table_name = f"archive_{dt.year}_{dt.month:02d}"
                except (ValueError, TypeError):
                    table_name = "archive_default"

                archive_conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        memory_id TEXT PRIMARY KEY,
                        user_id TEXT,
                        memory_type TEXT,
                        content_compressed BLOB,
                        summary TEXT,
                        importance REAL,
                        original_created_at TEXT,
                        archived_at TEXT NOT NULL
                    )
                """)

                content_bytes = (d.get("content", "") or "").encode("utf-8")
                compressed = gzip.compress(content_bytes)

                try:
                    archive_conn.execute(
                        f"INSERT OR IGNORE INTO {table_name}"
                        " (memory_id, user_id, memory_type, content_compressed, summary, importance, original_created_at, archived_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            d["memory_id"], d.get("user_id", ""), d.get("memory_type", "episodic"),
                            compressed, (d.get("summary", "") or "")[:1000],
                            d.get("importance", 0.5), d.get("created_at", ""), now,
                        ),
                    )
                    archived_count += 1
                except Exception:
                    pass

            archive_conn.commit()
        finally:
            archive_conn.close()

        # 主库删除（含 FTS + 向量表）
        for mid in memory_ids:
            try:
                conn.execute("DELETE FROM memory_entries WHERE memory_id=?", (mid,))
                conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (mid,))
                # 清理所有版本的 vec_memory 表
                try:
                    vec_tables = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'vec_memory%'"
                    ).fetchall()
                    for (vt,) in vec_tables:
                        conn.execute(f"DELETE FROM {vt} WHERE memory_id=?", (mid,))
                except Exception:
                    pass
            except Exception:
                pass
        conn.commit()

        logger.info("归档完成：%d 条 → %s", archived_count, archive_path)
        return archived_count
    finally:
        conn.close()
