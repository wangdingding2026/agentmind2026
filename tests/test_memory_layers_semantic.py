import sqlite3

import pytest

from agentmind.memory.types import MemoryEntry, MemoryType


def test_memory_cards_semantic_columns_exist_after_initialize():
    from agentmind.storage.db import DATA_DIR, initialize_memory_db

    initialize_memory_db()

    conn = sqlite3.connect(str(DATA_DIR / "memory.db"))
    try:
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(memory_cards)").fetchall()
        }
    finally:
        conn.close()

    assert {"card_text", "source_refs", "score_metadata", "session_id"} <= cols


@pytest.mark.asyncio
async def test_memory_card_semantic_fields_populated_on_insert():
    from agentmind.memory.sqlite_store import SqliteMemoryStore

    store = SqliteMemoryStore()
    entry = MemoryEntry(
        memory_id="semantic-card-1",
        content="Full raw source about retrieval cards",
        summary="Retrieval cards summarize raw memory",
        source_agent="agent-a",
        source_task_id="task-1",
        user_id="u1",
        memory_type=MemoryType.SEMANTIC,
        conversation_id="conv-1",
        importance=0.82,
        content_hash="hash-1",
        parent_id="parent-1",
        tags=["retrieval", "card"],
    )

    await store.insert(entry)

    card = await store.get_memory_card("semantic-card-1")

    assert card["card_text"] == "Retrieval cards summarize raw memory\n\nFull raw source about retrieval cards"
    assert card["session_id"] == "conv-1"
    assert card["source_refs"] == {
        "raw_memory_id": "semantic-card-1",
        "source_agent": "agent-a",
        "source_task_id": "task-1",
        "parent_id": "parent-1",
    }
    assert card["score_metadata"] == {
        "importance": 0.82,
        "memory_type": "semantic",
        "content_hash": "hash-1",
        "access_level": "shared",
    }


@pytest.mark.asyncio
async def test_semantic_card_enrichment_does_not_change_search_path():
    from agentmind.memory.service import MemoryService

    svc = MemoryService()
    await svc.write_memory({
        "memory_id": "semantic-search-compat-1",
        "content": "search should still use compatibility memory entries",
        "summary": "compat card search",
        "source_agent": "agent-a",
        "source_task_id": "task-1",
        "user_id": "u1",
        "tags": ["compat"],
    })

    rows = await svc.search_memory(query="compatibility memory entries", user_id="u1", limit=5)
    card = await svc.store.get_memory_card("semantic-search-compat-1")

    assert any(r["memory_id"] == "semantic-search-compat-1" for r in rows)
    assert "compat card search" in card["card_text"]


@pytest.mark.asyncio
async def test_retrieve_context_injects_confirmed_core_memory_only(tmp_path):
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    svc = MemoryService(repository=repo)
    await svc.write_memory({
        "memory_id": "core-source-1",
        "content": "我的项目是 AgentMind 记忆检索优化。",
        "summary": "AgentMind 项目偏好",
        "user_id": "u_core",
        "source_agent": "codex",
    })

    pending_ctx = await svc.retrieve_context(
        "我现在在做什么项目？",
        user_id="u_core",
        settings={"memory": {"working_memory_rounds": 3, "context_max_bytes": 4096}},
    )

    assert "core_memory" not in pending_ctx.steps

    assert await repo.confirm_core_memory("u_core", "current_projects") is True

    confirmed_ctx = await svc.retrieve_context(
        "我现在在做什么项目？",
        user_id="u_core",
        settings={"memory": {"working_memory_rounds": 3, "context_max_bytes": 4096}},
    )

    assert "core_memory" in confirmed_ctx.steps
    assert "AgentMind 记忆检索优化" in confirmed_ctx.assembled_context


@pytest.mark.asyncio
async def test_delete_memory_invalidates_core_and_relations(tmp_path):
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    svc = MemoryService(repository=repo)
    await svc.write_memory({
        "memory_id": "core-rel-source-1",
        "content": "我的项目是 AgentMind。参考：检索质量评估。",
        "summary": "AgentMind 项目",
        "user_id": "u_core_rel",
        "source_agent": "codex",
    })
    assert await repo.confirm_core_memory("u_core_rel", "current_projects") is True
    await repo.write_relations(
        "u_core_rel",
        [("core-rel-source-1", "references", "检索质量评估", "", 0.9)],
    )

    assert await repo.read_core_memory("u_core_rel")
    assert await repo.related_cards_for_query(
        query="检索质量评估",
        user_id="u_core_rel",
        limit=5,
    )

    await svc.delete_memory("core-rel-source-1")

    assert await repo.read_core_memory("u_core_rel") == ""
    assert await repo.related_cards_for_query(
        query="检索质量评估",
        user_id="u_core_rel",
        limit=5,
    ) == []


@pytest.mark.asyncio
async def test_retrieve_context_uses_memory_relations_for_lightweight_one_hop(tmp_path):
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    svc = MemoryService(repository=repo)
    await svc.write_memory({
        "memory_id": "relation-card-1",
        "content": "部署流程需要 blue-green release checklist。",
        "summary": "部署流程",
        "user_id": "u_relation",
        "source_agent": "codex",
        "tags": ["deploy"],
    })
    await repo.write_relations(
        "u_relation",
        [("relation-card-1", "references", "shadow traffic rehearsal", "", 0.9)],
    )

    ctx = await svc.retrieve_context(
        "shadow traffic rehearsal",
        user_id="u_relation",
        settings={"memory": {"working_memory_rounds": 3, "context_max_bytes": 4096}},
    )

    assert "relation_cards" in ctx.steps
    assert any(item["memory_id"] == "relation-card-1" for item in ctx.recall_items)
