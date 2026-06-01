"""Canonical memory schema owner."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def initialize_memory_storage(db_path: str) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode=WAL")
        ensure_canonical_tables(conn)
        conn.commit()
    finally:
        conn.close()


def ensure_canonical_tables(conn) -> None:
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
            source_kind TEXT NOT NULL DEFAULT 'task',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS memory_vectors (
            memory_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT '',
            embedding BLOB NOT NULL,
            dimension INTEGER NOT NULL DEFAULT 0,
            model TEXT NOT NULL DEFAULT '',
            version INTEGER NOT NULL DEFAULT 1,
            backend TEXT NOT NULL DEFAULT 'sqlite',
            updated_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS working_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            ts TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS session_state (
            user_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            force_new_next INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
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
    _add_columns(conn, "memory_cards", [
        ("card_text", "TEXT NOT NULL DEFAULT ''"),
        ("source_refs", "TEXT NOT NULL DEFAULT '{}'"),
        ("score_metadata", "TEXT NOT NULL DEFAULT '{}'"),
        ("session_id", "TEXT NOT NULL DEFAULT ''"),
        ("source_kind", "TEXT NOT NULL DEFAULT 'task'"),
    ])
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_raw_memory_user_created ON raw_memory(user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_raw_memory_task ON raw_memory(source_task_id)",
        "CREATE INDEX IF NOT EXISTS idx_memory_cards_user_created ON memory_cards(user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_memory_cards_raw ON memory_cards(raw_memory_id)",
        "CREATE INDEX IF NOT EXISTS idx_memory_vectors_user ON memory_vectors(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_memory_vectors_version ON memory_vectors(version)",
        "CREATE INDEX IF NOT EXISTS idx_memory_cards_conversation ON memory_cards(conversation_id)",
        "CREATE INDEX IF NOT EXISTS idx_memory_cards_session ON memory_cards(session_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_memory_cards_source_kind ON memory_cards(source_kind, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_memory_cards_type_importance ON memory_cards(memory_type, importance DESC)",
        "CREATE INDEX IF NOT EXISTS idx_working_memory_user_id ON working_memory(user_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_user_status ON sessions(user_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_conv_user_last ON conversations(user_id, last_message_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_conv_status ON conversations(status, last_message_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_rel_head ON memory_relations(user_id, head_entity)",
        "CREATE INDEX IF NOT EXISTS idx_rel_tail ON memory_relations(user_id, tail_entity)",
        "CREATE INDEX IF NOT EXISTS idx_rel_relation ON memory_relations(relation)",
        "CREATE INDEX IF NOT EXISTS idx_result_sets_user_created ON result_sets(user_id, created_at DESC)",
    ]
    for sql in indexes:
        conn.execute(sql)

def _add_columns(conn, table: str, columns: list[tuple[str, str]]) -> None:
    for name, definition in columns:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        except Exception:
            pass
