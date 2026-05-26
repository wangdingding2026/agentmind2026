"""v1 → v2 Schema 迁移执行器，幂等（检查 _schema_version 防重复）"""

import logging
import sqlite3

logger = logging.getLogger("agentmind")

_V2_COLUMNS = [
    ("memory_type", "TEXT DEFAULT 'episodic'"),
    ("conversation_id", "TEXT DEFAULT ''"),
    ("importance", "REAL DEFAULT 0.5"),
    ("content_hash", "TEXT DEFAULT ''"),
    ("embedding_model", "TEXT DEFAULT 'all-MiniLM-L6-v2'"),
    ("embedding_version", "INTEGER DEFAULT 1"),
    ("parent_id", "TEXT DEFAULT ''"),
    ("distilled", "INTEGER DEFAULT 0"),
    ("expire_at", "TEXT DEFAULT ''"),
]


def migrate_v1_to_v2(db_path: str) -> bool:
    """执行 v1 → v2 迁移。返回 True 表示执行了迁移，False 表示已是最新版本。"""
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute("PRAGMA busy_timeout = 5000")

    try:
        # 检查是否已迁移
        current = _get_version(conn)
        if current >= 2:
            logger.debug("memory.db 已是 v%d，跳过迁移", current)
            return False

        logger.info("开始迁移 memory.db v1 → v2")

        # 1. 逐列 ALTER TABLE（try/except 幂等）
        _add_columns(conn, "memory_entries", _V2_COLUMNS)

        # 2. 建新表（IF NOT EXISTS 幂等）
        _create_tables(conn)

        # 3. FTS5 迁移到 jieba（若可用）
        _migrate_fts5(conn)

        # 4. vec_memory 重命名为 vec_memory_v1
        _rename_vec_table(conn)

        # 5. core_memory status 列（pending → confirmed 审核机制）
        try:
            conn.execute(
                "ALTER TABLE core_memory ADD COLUMN status TEXT NOT NULL DEFAULT 'confirmed'"
            )
        except sqlite3.OperationalError:
            pass  # 列已存在

        # 7. 建索引（IF NOT EXISTS 幂等）
        _create_indexes(conn)

        # 8. 记录完成
        _record_version(conn, 2)

        conn.commit()
        logger.info("memory.db v1 → v2 迁移完成")
        return True
    except Exception as e:
        conn.rollback()
        logger.warning("memory.db 迁移失败: %s，数据库仍为 v1", e)
        return False
    finally:
        conn.close()


def ensure_memory_layer_tables(db_path: str):
    """确保 Phase 2 分层记忆表存在。幂等，可在每次启动时调用。"""
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS raw_memory (
                memory_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                source_agent TEXT NOT NULL DEFAULT '',
                source_task_id TEXT NOT NULL DEFAULT '',
                memory_type TEXT NOT NULL DEFAULT 'episodic',
                conversation_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                metadata TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS memory_cards (
                memory_id TEXT PRIMARY KEY,
                raw_memory_id TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                source_agent TEXT NOT NULL DEFAULT '',
                source_task_id TEXT NOT NULL DEFAULT '',
                memory_type TEXT NOT NULL DEFAULT 'episodic',
                conversation_id TEXT NOT NULL DEFAULT '',
                importance REAL NOT NULL DEFAULT 0.5,
                tags TEXT NOT NULL DEFAULT '[]',
                access_level TEXT NOT NULL DEFAULT 'shared',
                card_text TEXT NOT NULL DEFAULT '',
                source_refs TEXT NOT NULL DEFAULT '{}',
                score_metadata TEXT NOT NULL DEFAULT '{}',
                session_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                started_at TEXT NOT NULL DEFAULT '',
                ended_at TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                metadata TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS result_sets (
                result_set_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                query_text TEXT NOT NULL DEFAULT '',
                memory_ids TEXT NOT NULL DEFAULT '[]',
                cursor INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT '',
                expires_at TEXT NOT NULL DEFAULT '',
                metadata TEXT NOT NULL DEFAULT '{}'
            );
        """)
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_raw_memory_user_created ON raw_memory(user_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_raw_memory_task ON raw_memory(source_task_id)",
            "CREATE INDEX IF NOT EXISTS idx_memory_cards_user_created ON memory_cards(user_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_memory_cards_raw ON memory_cards(raw_memory_id)",
            "CREATE INDEX IF NOT EXISTS idx_memory_cards_conversation ON memory_cards(conversation_id)",
            "CREATE INDEX IF NOT EXISTS idx_memory_cards_session ON memory_cards(session_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_memory_cards_type_importance ON memory_cards(memory_type, importance DESC)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_user_status ON sessions(user_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_result_sets_user_created ON result_sets(user_id, created_at DESC)",
        ]
        _add_columns(conn, "memory_cards", [
            ("card_text", "TEXT NOT NULL DEFAULT ''"),
            ("source_refs", "TEXT NOT NULL DEFAULT '{}'"),
            ("score_metadata", "TEXT NOT NULL DEFAULT '{}'"),
            ("session_id", "TEXT NOT NULL DEFAULT ''"),
        ])
        for sql in indexes:
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


def _get_version(conn) -> int:
    try:
        row = conn.execute(
            "SELECT version FROM _schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def _add_columns(conn, table: str, columns: list[tuple[str, str]]):
    for col_name, col_def in columns:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass  # 列已存在，跳过


def _create_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            conversation_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            topic TEXT DEFAULT '',
            summary TEXT DEFAULT '',
            participant_agents TEXT DEFAULT '[]',
            message_count INTEGER DEFAULT 0,
            importance REAL DEFAULT 0.5,
            first_message_at TEXT NOT NULL DEFAULT '',
            last_message_at TEXT NOT NULL DEFAULT '',
            status TEXT DEFAULT 'active'
        );

        CREATE TABLE IF NOT EXISTS core_memory (
            user_id TEXT NOT NULL,
            slot_key TEXT NOT NULL,
            slot_value TEXT NOT NULL,
            byte_size INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT '',
            updated_by TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'confirmed',
            PRIMARY KEY (user_id, slot_key)
        );

        CREATE TABLE IF NOT EXISTS memory_relations (
            relation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL DEFAULT '',
            head_entity TEXT NOT NULL,
            relation TEXT NOT NULL,
            tail_entity TEXT NOT NULL,
            head_memory_id TEXT DEFAULT '',
            tail_memory_id TEXT DEFAULT '',
            confidence REAL DEFAULT 0.8,
            ts TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS procedural_signals (
            user_id TEXT NOT NULL,
            signal_key TEXT NOT NULL,
            signal_value TEXT NOT NULL DEFAULT '',
            weight REAL DEFAULT 1.0,
            hits INTEGER DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (user_id, signal_key)
        );
    """)


def _migrate_fts5(conn):
    """尝试用 jieba tokenizer 重建 FTS5 表，失败保留原表"""
    # 检查旧表是否存在
    old_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_fts'"
    ).fetchone()

    new_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_fts_v2'"
    ).fetchone()

    if new_exists:
        return  # 已经迁移过

    # 尝试建 jieba FTS5 表
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts_v2 USING fts5(
                memory_id, content, summary, tags,
                tokenize='jieba'
            )
        """)
        tokenizer = "jieba"
    except Exception:
        logger.debug("jieba tokenizer 不可用，降级到默认分词器")
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts_v2 USING fts5(
                memory_id, content, summary, tags
            )
        """)
        tokenizer = "default"

    # 从旧表或 memory_entries 回填
    if old_exists:
        _backfill_fts5(conn, "memory_fts", "memory_fts_v2")
        conn.execute("DROP TABLE IF EXISTS memory_fts")
    else:
        _backfill_fts5_entries(conn, "memory_fts_v2")

    # 重命名新表为 memory_fts
    conn.execute("DROP TABLE IF EXISTS memory_fts")
    conn.execute("ALTER TABLE memory_fts_v2 RENAME TO memory_fts")

    logger.info("FTS5 表迁移完成，tokenizer: %s", tokenizer)


def _backfill_fts5(conn, from_table: str, to_table: str):
    try:
        rows = conn.execute(f"SELECT memory_id, content, summary, tags FROM {from_table}").fetchall()
        for row in rows:
            try:
                conn.execute(
                    f"INSERT INTO {to_table}(memory_id, content, summary, tags) VALUES (?, ?, ?, ?)",
                    (row[0], row[1] or "", row[2] or "", row[3] or ""),
                )
            except Exception:
                pass
    except Exception:
        pass


def _backfill_fts5_entries(conn, to_table: str):
    try:
        rows = conn.execute("SELECT memory_id, content, summary, tags FROM memory_entries").fetchall()
        for row in rows:
            try:
                conn.execute(
                    f"INSERT INTO {to_table}(memory_id, content, summary, tags) VALUES (?, ?, ?, ?)",
                    (row[0], row[1] or "", row[2] or "", row[3] or ""),
                )
            except Exception:
                pass
    except Exception:
        pass


def _rename_vec_table(conn):
    """保留旧 vec_memory 不动（兼容旧代码路径），不重命名。
    未来切换 embedding 模型时由 EmbeddingMigrationWorker 创建 vec_memory_v2。"""
    # 不做重命名。旧代码在 storage/memory.py 直接引用 vec_memory，
    # 重命名会破坏 v4_write_enabled=false 的默认路径。
    pass


def _create_indexes(conn):
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_entries(memory_type, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_memory_conversation ON memory_entries(conversation_id)",
        "CREATE INDEX IF NOT EXISTS idx_memory_importance ON memory_entries(importance DESC, last_accessed_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_memory_hash ON memory_entries(content_hash)",
        "CREATE INDEX IF NOT EXISTS idx_conv_user_last ON conversations(user_id, last_message_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_conv_status ON conversations(status, last_message_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_rel_head ON memory_relations(user_id, head_entity)",
        "CREATE INDEX IF NOT EXISTS idx_rel_tail ON memory_relations(user_id, tail_entity)",
        "CREATE INDEX IF NOT EXISTS idx_rel_relation ON memory_relations(relation)",
    ]
    for sql in indexes:
        try:
            conn.execute(sql)
        except Exception:
            pass


def _record_version(conn, version: int):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT OR REPLACE INTO _schema_version (version, applied_at) VALUES (?, ?)",
        (version, now),
    )
