import sqlite3

import pytest

from agentmind.memory.types import MemoryEntry


def test_memory_layer_tables_exist_after_initialize():
    from agentmind.storage.db import DATA_DIR, initialize_memory_db

    initialize_memory_db()

    conn = sqlite3.connect(str(DATA_DIR / "memory.db"))
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual')"
            ).fetchall()
        }
    finally:
        conn.close()

    assert {"raw_memory", "memory_cards", "sessions", "result_sets"} <= tables


@pytest.mark.asyncio
async def test_repository_writes_raw_memory_and_memory_card():
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository

    repo = SqliteMemoryRepository()
    entry = MemoryEntry(
        memory_id="m-layer-1",
        content="raw original content",
        summary="card summary",
        source_agent="agent-a",
        source_task_id="task-1",
        user_id="u1",
        tags=["layer", "test"],
    )

    await repo.write_raw_and_card(MemoryWriteCommand(
        memory_id=entry.memory_id,
        content=entry.content,
        summary=entry.summary,
        source_agent=entry.source_agent,
        source_task_id=entry.source_task_id,
        user_id=entry.user_id,
        tags=entry.tags,
    ))

    raw = await repo.get_raw("m-layer-1")
    card = await repo.get_card("m-layer-1")

    assert raw["memory_id"] == "m-layer-1"
    assert raw["content"] == "raw original content"
    assert raw["user_id"] == "u1"
    assert card["memory_id"] == "m-layer-1"
    assert card["summary"] == "card summary"
    assert card["tags"] == ["layer", "test"]


@pytest.mark.asyncio
async def test_memory_service_write_populates_layers_for_card_search():
    from agentmind.memory.service import MemoryService

    svc = MemoryService()
    await svc.write_memory({
        "memory_id": "svc-layer-1",
        "content": "memory layers keep unified card search",
        "summary": "unified card search",
        "source_agent": "agent-a",
        "source_task_id": "task-1",
        "user_id": "u1",
        "tags": ["unified"],
    })

    rows = await svc.search_memory(query="unified", user_id="u1", limit=5)
    card = await svc.store.get_card("svc-layer-1")

    assert any(r["memory_id"] == "svc-layer-1" for r in rows)
    assert card["summary"] == "unified card search"
