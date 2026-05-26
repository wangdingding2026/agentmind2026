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
