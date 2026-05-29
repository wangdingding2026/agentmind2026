import asyncio
import sqlite3


def test_initialize_memory_storage_creates_only_canonical_tables(tmp_path):
    from agentmind.memory.schema import initialize_memory_storage

    db_path = tmp_path / "memory.db"
    initialize_memory_storage(str(db_path))

    conn = sqlite3.connect(str(db_path))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')"
            ).fetchall()
        }
    finally:
        conn.close()

    assert {
        "raw_memory",
        "memory_cards",
        "working_memory",
        "core_memory",
        "memory_relations",
        "result_sets",
        "conversations",
    }.issubset(tables)
    assert "memory_entries" not in tables
    assert "memory_fts" not in tables


def test_repository_write_raw_and_card_same_transaction(tmp_path):
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))

    row = asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        content="登录超时通过 session ttl 7200 解决。",
        summary="登录超时修复",
        user_id="u1",
        source_agent="codex",
        source_task_id="trace-1",
        tags=["login"],
    )))

    assert row["memory_id"]
    results = asyncio.run(repo.search_cards(query="登录超时", user_id="u1", limit=5))
    assert results
    assert results[0]["raw_memory_id"] == row["raw_memory_id"]


def test_repository_result_set_expand_reads_card_and_raw(tmp_path):
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    first = asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        content="第一条完整原文",
        summary="第一条卡片",
        user_id="u1",
    )))
    second = asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        content="第二条完整原文",
        summary="第二条卡片",
        user_id="u1",
    )))

    result_set_id = asyncio.run(repo.create_result_set(
        user_id="u1",
        query_text="完整原文",
        items=[first, second],
    ))
    expanded = asyncio.run(repo.expand_result(result_set_id, 2, user_id="u1"))

    assert expanded["memory_id"] == second["memory_id"]
    assert expanded["content"] == "第二条完整原文"
    assert expanded["card"]["summary"] == "第二条卡片"


def test_repository_working_memory_and_active_conversation(tmp_path):
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))

    asyncio.run(repo.append_working_memory("u1", "user", "hello"))
    asyncio.run(repo.append_working_memory("u1", "assistant", "world"))
    rounds = asyncio.run(repo.get_working_memory("u1", limit=1))

    conn = repo._get_conn()
    try:
        conn.execute(
            """INSERT INTO conversations
               (conversation_id, user_id, first_message_at, last_message_at, status)
               VALUES (?, ?, ?, ?, ?)""",
            ("conv-repo-active", "u1", "2026-05-29 09:00:00", "2026-05-29 10:00:00", "active"),
        )
        conn.commit()
    finally:
        conn.close()

    assert rounds == [{"user": "hello", "assistant": "world", "ts": rounds[0]["ts"]}]
    assert asyncio.run(repo.get_active_conversation_id("u1")) == "conv-repo-active"
