import pytest


@pytest.mark.asyncio
async def test_v4_retrieval_pipeline_uses_memory_cards_for_recall():
    from agentmind.memory.service import MemoryService

    svc = MemoryService()
    await svc.write_memory({
        "memory_id": "pipeline-card-1",
        "content": "raw transcript for pipeline card search",
        "summary": "pipeline card recall summary",
        "source_agent": "codex",
        "source_task_id": "pipeline-card-task",
        "user_id": "u_pipeline_cards",
        "tags": ["pipeline", "cards"],
        "access_level": "shared",
    })

    result = await svc.retrieve(
        "pipeline card recall",
        user_id="u_pipeline_cards",
        settings={
            "memory": {
                "v4_retrieval_enabled": True,
                "retrieval_max_candidates": 10,
                "context_max_bytes": 4096,
            }
        },
    )

    recall_items = result["recall_items"]

    assert [item["memory_id"] for item in recall_items] == ["pipeline-card-1"]
    assert recall_items[0]["_route"] == "memory_cards"
    assert "pipeline card recall summary" in result["assembled_context"]


@pytest.mark.asyncio
async def test_v4_retrieval_keeps_current_session_context_out_of_historical_recall():
    from agentmind.memory.service import MemoryService
    from agentmind.memory.types import MemoryEntry

    svc = MemoryService()
    conn = svc.store._get_conn()
    try:
        conn.execute(
            """INSERT INTO conversations
               (conversation_id, user_id, first_message_at, last_message_at, status)
               VALUES (?, ?, ?, ?, ?)""",
            ("conv-current-boundary", "u_boundary", "2026-05-25 09:00:00", "2026-05-25 10:00:00", "active"),
        )
        conn.execute(
            """INSERT INTO conversations
               (conversation_id, user_id, first_message_at, last_message_at, status)
               VALUES (?, ?, ?, ?, ?)""",
            ("conv-history-boundary", "u_boundary", "2026-05-24 09:00:00", "2026-05-24 10:00:00", "closed"),
        )
        conn.commit()
    finally:
        conn.close()

    svc.add_to_working_memory("u_boundary", "user", "current session says deploy port 8765")
    svc.add_to_working_memory("u_boundary", "assistant", "current session answer keeps port 8765")

    await svc.store.insert(MemoryEntry(
        memory_id="current-card-boundary",
        content="current session historical recall duplicate deployment port 8765",
        summary="current session deployment card should stay out of historical recall",
        user_id="u_boundary",
        conversation_id="conv-current-boundary",
        tags=["deployment"],
        access_level="shared",
    ))
    await svc.store.insert(MemoryEntry(
        memory_id="history-card-boundary",
        content="historical deployment notes mention nginx timeout",
        summary="historical card should be recalled",
        user_id="u_boundary",
        conversation_id="conv-history-boundary",
        tags=["deployment"],
        access_level="shared",
    ))

    result = await svc.retrieve(
        "deployment",
        user_id="u_boundary",
        settings={
            "memory": {
                "v4_retrieval_enabled": True,
                "working_memory_rounds": 3,
                "retrieval_max_candidates": 10,
                "context_max_bytes": 4096,
            }
        },
    )

    recall_ids = [item["memory_id"] for item in result["recall_items"]]

    assert "history-card-boundary" in recall_ids
    assert "current-card-boundary" not in recall_ids
    assert "current session says deploy port 8765" in result["assembled_context"]
    assert "historical card should be recalled" in result["assembled_context"]
