import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentmind.services.task_service import TaskService as TaskService

TaskService = None

logger = logging.getLogger("agentmind")

DATA_HOME = Path.home() / ".agentmind"
DATA_DIR = DATA_HOME / "data"
CONFIG_DIR = DATA_HOME / "config"
LOGS_DIR = DATA_HOME / "logs"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db_connection():
    """获取 history.db 的数据库连接"""
    conn = sqlite3.connect(str(DATA_DIR / "history.db"), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def initialize_data_directory():
    """首次启动时创建所有目录和数据库文件"""
    for dir_path in [DATA_DIR / "results", CONFIG_DIR, LOGS_DIR]:
        dir_path.mkdir(parents=True, exist_ok=True)

    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_history (
            trace_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            user_message TEXT NOT NULL,
            matched_rule TEXT,
            routed_agent TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'routing', 'executing', 'completed', 'failed', 'timeout')),
            result_summary TEXT,
            full_result_path TEXT,
            execution_time_ms INTEGER,
            error_message TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON task_history(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON task_history(status)")
    # v2.0 新增列：崩溃恢复
    for col, col_def in [
        ("can_retry", "BOOLEAN DEFAULT FALSE"),
        ("retry_context", "TEXT"),
        ("is_retry", "BOOLEAN DEFAULT FALSE"),
    ]:
        try:
            conn.execute(f"ALTER TABLE task_history ADD COLUMN {col} {col_def}")
        except Exception:
            pass  # 列已存在则跳过
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()
    conn.close()

    meta_file = DATA_DIR / "meta.json"
    if not meta_file.exists():
        meta_file.write_text(json.dumps({"data_version": 1, "created_at": now_iso()}))

    # v2.0 记忆数据库
    initialize_memory_db()
    # v3.0 Attach 对话表
    _init_attach_db()


_VEC_AVAILABLE = False


def _try_load_sqlite_vec():
    """尝试加载 sqlite-vec 扩展，失败则全局标记不可用"""
    global _VEC_AVAILABLE
    try:
        import sqlite_vec
        _VEC_AVAILABLE = True
        return sqlite_vec
    except Exception:
        _VEC_AVAILABLE = False
        return None


def initialize_memory_db():
    """初始化记忆数据库 memory.db，含向量搜索和 FTS5 全文索引"""
    conn = sqlite3.connect(str(DATA_DIR / "memory.db"), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")

    # 核心表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_entries (
            memory_id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            summary TEXT NOT NULL,
            source_agent TEXT NOT NULL,
            source_task_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            access_level TEXT NOT NULL DEFAULT 'shared',
            tags TEXT,
            version INTEGER DEFAULT 1
        )
    """)

    # 新增列（迁移兼容）
    for col, col_def in [
        ("embedding", "BLOB"),
        ("user_id", "TEXT"),
        ("last_accessed_at", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE memory_entries ADD COLUMN {col} {col_def}")
        except Exception:
            pass

    # 索引
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_source ON memory_entries(source_agent, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_user ON memory_entries(user_id, created_at)")

    # FTS5 全文搜索虚拟表（独立表，手动同步）
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
            memory_id, content, summary, tags
        )
    """)

    # sqlite-vec 向量索引
    vec = _try_load_sqlite_vec()
    if vec is not None:
        try:
            conn.enable_load_extension(True)
            vec.load(conn)
            # 读取 embedding_dim 配置
            import yaml
            dim = 384
            settings_path = CONFIG_DIR / "settings.yaml"
            if settings_path.exists():
                try:
                    data = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
                    if isinstance(data, dict):
                        emb_cfg = data.get("embedding", {})
                        dim = int(emb_cfg.get("dimension", 768))
                except Exception:
                    pass
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS vec_memory USING vec0("
                f"  memory_id TEXT PRIMARY KEY, embedding FLOAT[{dim}]"
                ")"
            )
        except Exception:
            pass  # sqlite-vec 不可用时静默跳过

    conn.commit()
    conn.close()

    # v4 迁移：尝试将 schema 从 v1 升级到 v2
    try:
        from agentmind.memory.migrations.runner import ensure_memory_layer_tables, migrate_v1_to_v2
        migrate_v1_to_v2(str(DATA_DIR / "memory.db"))
        ensure_memory_layer_tables(str(DATA_DIR / "memory.db"))
    except Exception as e:
        logger.debug("v4 迁移跳过: %s", e)


def is_vec_available() -> bool:
    """检查 sqlite-vec 向量搜索是否可用"""
    return _VEC_AVAILABLE


# ========== 异步安全的任务记录函数 ==========


def _task_service():
    global TaskService
    if TaskService is None:
        from agentmind.services.task_service import TaskService as _TaskService
        TaskService = _TaskService
    return TaskService()

def _record_task_start_sync(trace_id: str, user_message: str):
    conn = get_db_connection()
    conn.execute(
        """INSERT INTO task_history (trace_id, created_at, updated_at, user_message, status)
           VALUES (?, ?, ?, ?, ?)""",
        (trace_id, now_iso(), now_iso(), user_message[:1000], "pending"),
    )
    conn.commit()
    conn.close()


async def record_task_start(trace_id: str, user_message: str):
    await _task_service().start_task(trace_id, user_message)


def _record_task_update_sync(trace_id: str, status: str, matched_rule: str = None, routed_agent: str = None):
    conn = get_db_connection()
    updates = {"status": status, "updated_at": now_iso()}
    if matched_rule is not None:
        updates["matched_rule"] = matched_rule
    if routed_agent is not None:
        updates["routed_agent"] = routed_agent
    set_clause = ", ".join(f"{k}=?" for k in updates.keys())
    values = list(updates.values()) + [trace_id]
    conn.execute(f"UPDATE task_history SET {set_clause} WHERE trace_id=?", values)
    conn.commit()
    conn.close()


async def record_task_update(trace_id: str, status: str, matched_rule: str = None, routed_agent: str = None):
    await _task_service().update_task(trace_id, status, matched_rule, routed_agent)


_MAX_RESULT_SIZE = 100 * 1024  # 100KB


def _load_history_settings() -> dict:
    """读取 history 相关配置"""
    import yaml
    settings_path = CONFIG_DIR / "settings.yaml"
    if not settings_path.exists():
        return {}
    try:
        data = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
        return data.get("history", {}) if isinstance(data, dict) else {}
    except Exception:
        return {}


def _enforce_history_lru(conn: sqlite3.Connection):
    """检查 history.db 容量，超限时按 LRU 淘汰最旧记录"""
    cfg = _load_history_settings()
    max_entries = cfg.get("max_entries", 10000)
    if max_entries <= 0:
        return  # 0 = 不限制
    retention_days = cfg.get("retention_days", 30)

    total = conn.execute("SELECT COUNT(*) as cnt FROM task_history").fetchone()["cnt"]
    if total < max_entries:
        return

    evict_count = max(1, int(total * 0.1))
    deadline = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()

    # 找出可淘汰的记录（超过保留期限且最旧），收集 trace_id 用于后续级联清理
    rows = conn.execute(
        """SELECT trace_id FROM task_history
           WHERE created_at < ?
           ORDER BY created_at ASC LIMIT ?""",
        (deadline, evict_count),
    ).fetchall()
    trace_ids = [r["trace_id"] for r in rows]
    if not trace_ids:
        return

    placeholders = ",".join("?" for _ in trace_ids)
    conn.execute(f"DELETE FROM task_history WHERE trace_id IN ({placeholders})", trace_ids)

    # 级联清理 attached_conversations
    try:
        conn.execute(
            f"DELETE FROM attached_conversations WHERE trace_id IN ({placeholders})", trace_ids
        )
    except Exception:
        pass

    # 级联清理 results/*.txt 文件
    for tid in trace_ids:
        try:
            result_file = DATA_DIR / "results" / f"{tid}.txt"
            if result_file.exists():
                os.remove(result_file)
        except Exception:
            pass

    conn.commit()
    logger.info("历史 LRU 淘汰：%d 条（上限 %d，保留 %d 天）", len(trace_ids), max_entries, retention_days)


def _save_result_sync(
    trace_id: str,
    status: str,
    agent_id: str = None,
    execution_time_ms: int = None,
    error_message: str = None,
    result: str = None,
):
    conn = get_db_connection()
    updates = {
        "status": status,
        "updated_at": now_iso(),
        "routed_agent": agent_id,
        "execution_time_ms": execution_time_ms,
        "error_message": error_message,
    }
    if result is not None:
        # 一次编码，按字节判断是否超限
        result_bytes = result.encode("utf-8")
        if len(result_bytes) > _MAX_RESULT_SIZE:
            result = (
                result_bytes[:_MAX_RESULT_SIZE].decode("utf-8", errors="replace")
                + "\n...[截断：结果超过100KB]"
            )
        summary = result[:500] + ("..." if len(result) > 500 else "")
        result_path = DATA_DIR / "results" / f"{trace_id}.txt"
        result_path.parent.mkdir(exist_ok=True)
        result_path.write_text(result, encoding="utf-8")
        updates["result_summary"] = summary
        updates["full_result_path"] = str(result_path)

    set_clause = ", ".join(f"{k}=?" for k in updates.keys())
    values = list(updates.values()) + [trace_id]
    conn.execute(f"UPDATE task_history SET {set_clause} WHERE trace_id=?", values)
    conn.commit()
    _enforce_history_lru(conn)
    conn.close()


async def record_task_end(
    trace_id: str,
    status: str,
    agent_id: str = None,
    execution_time_ms: int = None,
    error_message: str = None,
    result: str = None,
):
    await _task_service().end_task(
        trace_id, status, agent_id, execution_time_ms, error_message, result
    )


# ========== 查询函数 ==========

def _query_tasks_sync(limit: int = 20, offset: int = 0, status: str = None) -> list[dict]:
    conn = get_db_connection()
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    if status:
        rows = conn.execute(
            """SELECT trace_id, created_at, user_message, matched_rule, routed_agent,
                      status, execution_time_ms, error_message
               FROM task_history WHERE status=? ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (status, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT trace_id, created_at, user_message, matched_rule, routed_agent,
                      status, execution_time_ms, error_message
               FROM task_history ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


async def query_tasks(limit: int = 20, offset: int = 0, status: str = None) -> list[dict]:
    return await asyncio.to_thread(_query_tasks_sync, limit, offset, status)


def _get_task_stats_sync() -> dict:
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM task_history GROUP BY status"
    ).fetchall()
    stats = {"total": 0, "completed": 0, "failed": 0, "routing": 0, "executing": 0, "pending": 0}
    for r in rows:
        stats["total"] += r["cnt"]
        if r["status"] in stats:
            stats[r["status"]] = r["cnt"]
    avg_row = conn.execute(
        "SELECT AVG(execution_time_ms) as avg_ms FROM task_history WHERE status='completed'"
    ).fetchone()
    stats["avg_execution_time_ms"] = round(avg_row["avg_ms"] or 0)
    conn.close()
    return stats


async def get_task_stats() -> dict:
    return await asyncio.to_thread(_get_task_stats_sync)


def _get_task_detail_sync(trace_id: str) -> dict | None:
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM task_history WHERE trace_id=?", (trace_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


async def get_task_detail(trace_id: str) -> dict | None:
    return await asyncio.to_thread(_get_task_detail_sync, trace_id)


def _get_recent_errors_sync(limit: int = 5) -> list[dict]:
    limit = max(1, min(limit, 50))
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT trace_id, created_at, routed_agent, error_message
           FROM task_history WHERE status='failed' ORDER BY created_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


async def get_recent_errors(limit: int = 5) -> list[dict]:
    return await asyncio.to_thread(_get_recent_errors_sync, limit)


# ========== v2.0 崩溃恢复 ==========

def _load_heartbeat_timeout() -> int:
    """从 settings.yaml 读取心跳超时阈值（秒），默认 300"""
    import yaml
    settings_path = CONFIG_DIR / "settings.yaml"
    if settings_path.exists():
        try:
            data = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                return int(data.get("heartbeat_timeout_seconds", 300))
        except Exception:
            pass
    return 300


def mark_timed_out_tasks_retriable():
    """崩溃恢复：将长时间处于 executing 状态的任务标记为可重试"""
    timeout_seconds = _load_heartbeat_timeout()
    conn = get_db_connection()
    cutoff = datetime.now(timezone.utc).isoformat()
    # 找到超时的 executing 任务
    rows = conn.execute(
        """SELECT trace_id, user_message FROM task_history
           WHERE status='executing'
           AND datetime(updated_at) < datetime(?, ?)""",
        (cutoff, f"-{timeout_seconds} seconds"),
    ).fetchall()
    for row in rows:
        conn.execute(
            """UPDATE task_history SET status='failed', can_retry=TRUE,
               retry_context=?, is_retry=FALSE WHERE trace_id=?""",
            (json.dumps({"user_message": row["user_message"]}), row["trace_id"]),
        )
    if rows:
        logging.getLogger("agentmind").info("崩溃恢复：标记了 %d 个超时任务为可重试", len(rows))
    conn.commit()
    conn.close()


# ========== v2.0 可观测性 ==========

def _get_metrics_sync() -> dict:
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT execution_time_ms FROM task_history WHERE status='completed' AND execution_time_ms IS NOT NULL ORDER BY execution_time_ms"
    ).fetchall()
    times = sorted([r["execution_time_ms"] for r in rows])
    n = len(times)
    p50 = times[n // 2] if n else 0
    p90 = times[int(n * 0.9)] if n else 0
    p99 = times[int(n * 0.99)] if n else 0

    agent_errors = {}
    for r in conn.execute(
        "SELECT routed_agent, COUNT(*) as total, SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as errors FROM task_history WHERE routed_agent IS NOT NULL GROUP BY routed_agent"
    ).fetchall():
        agent_errors[r["routed_agent"]] = {
            "total": r["total"], "errors": r["errors"],
            "error_rate": round(r["errors"] / r["total"], 3) if r["total"] > 0 else 0,
        }

    recent = conn.execute(
        "SELECT COUNT(*) as cnt FROM task_history WHERE created_at > datetime('now', '-1 hour')"
    ).fetchone()["cnt"]
    conn.close()
    return {"latency_ms": {"p50": p50, "p90": p90, "p99": p99}, "by_agent": agent_errors, "throughput_1h": recent}


async def get_metrics() -> dict:
    return await asyncio.to_thread(_get_metrics_sync)


# ========== v3.0 Attach 对话持久化 ==========

def _init_attach_db():
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attached_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT NOT NULL,
            user_message TEXT NOT NULL,
            agent_response TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (trace_id) REFERENCES task_history(trace_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_attached_trace ON attached_conversations(trace_id, created_at)")
    conn.commit()
    conn.close()


def _record_attached_turn_sync(trace_id: str, user_message: str, agent_response: str):
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO attached_conversations (trace_id, user_message, agent_response, created_at) VALUES (?, ?, ?, ?)",
        (trace_id, user_message, agent_response, now_iso()),
    )
    conn.commit()
    conn.close()


async def record_attached_turn(trace_id: str, user_message: str, agent_response: str):
    await _task_service().record_attached_turn(trace_id, user_message, agent_response)
