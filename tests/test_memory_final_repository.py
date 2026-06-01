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
        "memory_vectors",
        "knowledge_items",
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


def test_repository_persists_and_filters_source_kind(tmp_path):
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="turn-1",
        content="今天问了你是谁",
        summary="[agentmind] 我是 AgentMind",
        user_id="u_source_kind",
        source_agent="agentmind",
        source_kind="conversation_turn",
        created_at="2026-05-29 09:00:00",
    )))
    asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="fact-1",
        content="AgentMind 是路由器",
        summary="事实",
        user_id="u_source_kind",
        source_agent="agentmind",
        source_kind="fact",
        created_at="2026-05-29 09:01:00",
    )))

    rows = asyncio.run(repo.search_cards(
        query="",
        user_id="u_source_kind",
        source_kinds=["conversation_turn"],
        limit=10,
    ))

    assert [row["memory_id"] for row in rows] == ["turn-1"]
    assert rows[0]["source_kind"] == "conversation_turn"


def test_repository_vector_write_and_search_uses_sqlite_fallback(tmp_path):
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.provider import embedding_to_blob
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="vector-deploy",
        content="部署端口 8765 需要保留给 AgentMind 服务。",
        summary="部署端口 8765",
        user_id="u_vector",
        access_level="shared",
    )))
    asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="vector-cooking",
        content="晚餐需要准备番茄鸡蛋。",
        summary="晚餐菜单",
        user_id="u_vector",
        access_level="shared",
    )))
    asyncio.run(repo.write_vector_embedding(
        ["vector-deploy"],
        embedding_to_blob([1.0, 0.0]),
        model="fake-2d",
        version=2,
    ))
    asyncio.run(repo.write_vector_embedding(
        ["vector-cooking"],
        embedding_to_blob([0.0, 1.0]),
        model="fake-2d",
        version=2,
    ))

    rows = asyncio.run(repo.search_vector(
        query_embedding=[0.99, 0.01],
        user_id="u_vector",
        access_levels=["shared"],
        limit=2,
    ))

    assert [row["memory_id"] for row in rows] == ["vector-deploy", "vector-cooking"]
    assert rows[0]["_route"] == "memory_vectors"
    assert rows[0]["_score"] > rows[1]["_score"]
    stats = asyncio.run(repo.get_stats())
    assert stats["vector_search_enabled"] is True
    assert stats["with_embedding"] == 2


def test_repository_rebuild_vector_index_generates_missing_vectors(tmp_path, monkeypatch):
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="rebuild-deploy",
        content="部署端口 8765",
        summary="部署端口",
        user_id="u_rebuild",
        access_level="shared",
        embedding_version=1,
    )))
    asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="rebuild-menu",
        content="晚餐番茄鸡蛋",
        summary="晚餐",
        user_id="u_rebuild",
        access_level="shared",
        embedding_version=1,
    )))

    def fake_generate_embedding_sync(text, settings=None):
        if "部署" in text:
            return [1.0, 0.0]
        return [0.0, 1.0]

    monkeypatch.setattr(
        "agentmind.memory.repository_sqlite.generate_embedding_sync",
        fake_generate_embedding_sync,
    )

    rebuilt = asyncio.run(repo.rebuild_vector_index(
        target_version=2,
        model="fake-2d",
        limit=10,
    ))
    rows = asyncio.run(repo.search_vector(
        query_embedding=[1.0, 0.0],
        user_id="u_rebuild",
        limit=2,
    ))
    menu_rows = asyncio.run(repo.search_vector(
        query_embedding=[0.0, 1.0],
        user_id="u_rebuild",
        limit=2,
    ))

    assert rebuilt == 2
    assert [row["memory_id"] for row in rows] == ["rebuild-deploy"]
    assert [row["memory_id"] for row in menu_rows] == ["rebuild-menu"]


# ── read_conversation_turns ──


def test_read_conversation_turns_returns_question_and_answer(tmp_path):
    """question 来自 raw_memory.content，answer 来自 memory_cards.summary"""
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="turn-q1",
        content="你会写代码吗？",
        summary="[agentmind] 可以路由给 codex。",
        user_id="u_turns",
        source_agent="agentmind",
        source_kind="conversation_turn",
        conversation_id="conv-turns-1",
        created_at="2026-05-29 09:00:00",
    )))

    rows = asyncio.run(repo.read_conversation_turns(
        user_id="u_turns",
        conversation_id="conv-turns-1",
    ))

    assert len(rows) == 1
    assert rows[0]["question"] == "你会写代码吗？"
    assert rows[0]["answer"] == "可以路由给 codex。"
    assert rows[0]["source_agent"] == "agentmind"
    assert rows[0]["source_kind"] == "conversation_turn"


def test_read_conversation_turns_strips_agent_prefix_from_answer(tmp_path):
    """去掉 summary 前缀 [agentmind]"""
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="turn-prefix",
        content="你能做什么？",
        summary="[agentmind] 我是路由器",
        user_id="u_prefix",
        source_agent="agentmind",
        source_kind="conversation_turn",
        created_at="2026-05-29 10:00:00",
    )))

    rows = asyncio.run(repo.read_conversation_turns(user_id="u_prefix"))
    assert rows[0]["answer"] == "我是路由器"


def test_read_conversation_turns_does_not_use_card_text_as_question(tmp_path):
    """question 来自 raw_memory.content，不是 card_text"""
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="turn-cardtext",
        content="用户原始问题",
        summary="[agentmind] 卡片摘要",
        user_id="u_cardtext",
        source_agent="agentmind",
        source_kind="conversation_turn",
        created_at="2026-05-29 10:00:00",
    )))

    rows = asyncio.run(repo.read_conversation_turns(user_id="u_cardtext"))
    assert rows[0]["question"] == "用户原始问题"


def test_read_conversation_turns_excludes_history_answers_by_default(tmp_path):
    """默认排除 source_kind = conversation_history_answer"""
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="turn-normal",
        content="正常问题",
        summary="[agentmind] 正常回答",
        user_id="u_exclude",
        source_agent="agentmind",
        source_kind="conversation_turn",
        created_at="2026-05-29 09:00:00",
    )))
    asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="turn-history",
        content="今天聊过什么",
        summary="[agentmind] 今天的对话记录：...",
        user_id="u_exclude",
        source_agent="agentmind",
        source_kind="conversation_history_answer",
        created_at="2026-05-29 09:05:00",
    )))

    rows = asyncio.run(repo.read_conversation_turns(user_id="u_exclude"))
    ids = [r["memory_id"] for r in rows]
    assert "turn-normal" in ids
    assert "turn-history" not in ids


def test_read_conversation_turns_can_include_history_answers(tmp_path):
    """include_history_answers=True 时包含历史查询答案"""
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="turn-hist2",
        content="今天聊过什么",
        summary="[agentmind] 今天的对话记录：...",
        user_id="u_include",
        source_agent="agentmind",
        source_kind="conversation_history_answer",
        created_at="2026-05-29 09:05:00",
    )))

    rows = asyncio.run(repo.read_conversation_turns(
        user_id="u_include",
        include_history_answers=True,
    ))
    ids = [r["memory_id"] for r in rows]
    assert "turn-hist2" in ids


def test_read_conversation_turns_filters_by_conversation_id(tmp_path):
    """可以按 conversation_id 过滤"""
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="turn-conv-a",
        content="问题A",
        summary="[agentmind] 回答A",
        user_id="u_conv",
        source_agent="agentmind",
        source_kind="conversation_turn",
        conversation_id="conv-a",
        created_at="2026-05-29 09:00:00",
    )))
    asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="turn-conv-b",
        content="问题B",
        summary="[agentmind] 回答B",
        user_id="u_conv",
        source_agent="agentmind",
        source_kind="conversation_turn",
        conversation_id="conv-b",
        created_at="2026-05-29 09:01:00",
    )))

    rows = asyncio.run(repo.read_conversation_turns(
        user_id="u_conv",
        conversation_id="conv-a",
    ))
    assert len(rows) == 1
    assert rows[0]["question"] == "问题A"


def test_read_conversation_turns_filters_by_time_range(tmp_path):
    """可以按时间范围过滤（today/yesterday）"""
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="turn-today",
        content="今天的问题",
        summary="[agentmind] 今天的回答",
        user_id="u_timerange",
        source_agent="agentmind",
        source_kind="conversation_turn",
        created_at="2026-05-29 09:00:00",
    )))
    asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="turn-yesterday",
        content="昨天的问题",
        summary="[agentmind] 昨天的回答",
        user_id="u_timerange",
        source_agent="agentmind",
        source_kind="conversation_turn",
        created_at="2026-05-28 09:00:00",
    )))

    rows = asyncio.run(repo.read_conversation_turns(
        user_id="u_timerange",
        time_range_start="2026-05-29 00:00:00",
        time_range_end="2026-05-29 23:59:59",
    ))
    ids = [r["memory_id"] for r in rows]
    assert "turn-today" in ids
    assert "turn-yesterday" not in ids


def test_read_conversation_turns_ordered_by_time_asc(tmp_path):
    """按时间正序输出"""
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="turn-late",
        content="晚的问题",
        summary="[agentmind] 晚的回答",
        user_id="u_order",
        source_agent="agentmind",
        source_kind="conversation_turn",
        created_at="2026-05-29 15:00:00",
    )))
    asyncio.run(repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="turn-early",
        content="早的问题",
        summary="[agentmind] 早的回答",
        user_id="u_order",
        source_agent="agentmind",
        source_kind="conversation_turn",
        created_at="2026-05-29 09:00:00",
    )))

    rows = asyncio.run(repo.read_conversation_turns(user_id="u_order"))
    assert rows[0]["question"] == "早的问题"
    assert rows[1]["question"] == "晚的问题"
