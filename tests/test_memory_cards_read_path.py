from pathlib import Path

import pytest
import yaml

from agentmind.memory.types import MemoryEntry, MemoryType


@pytest.mark.asyncio
async def test_memory_service_search_memory_cards_reads_card_text_not_raw_chatter():
    from agentmind.memory.service import MemoryService

    svc = MemoryService()
    await svc.write_memory(MemoryEntry(
        memory_id="card-read-1",
        content="large raw transcript contains implementation chatter only",
        summary="Memory cards are the retrieval surface",
        user_id="u_cards",
        source_agent="codex",
        source_task_id="task-card",
        memory_type=MemoryType.SEMANTIC,
        conversation_id="sess-cards",
        importance=0.9,
        tags=["architecture", "memory"],
        access_level="shared",
        created_at="2026-05-25 10:00:00",
    ).to_dict())

    rows = await svc.search_memory_cards(
        query="retrieval surface",
        user_id="u_cards",
        limit=5,
    )

    assert [r["memory_id"] for r in rows] == ["card-read-1"]
    assert rows[0]["raw_memory_id"] == "card-read-1"
    assert rows[0]["card_text"].startswith("Memory cards are the retrieval surface")
    assert rows[0]["source_refs"]["source_agent"] == "codex"
    assert rows[0]["score_metadata"]["memory_type"] == "semantic"
    assert rows[0]["_route"] == "memory_cards"


@pytest.mark.asyncio
async def test_memory_service_search_memory_cards_filters_and_orders_results():
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    repo = SqliteMemoryRepository()
    svc = MemoryService(repository=repo)
    entries = [
        MemoryEntry(
            memory_id="card-rank-old-important",
            content="raw alpha",
            summary="database boundary card",
            user_id="u_filter",
            memory_type=MemoryType.SEMANTIC,
            conversation_id="sess-filter",
            importance=0.95,
            tags=["database", "trace"],
            access_level="shared",
            created_at="2026-05-24 09:00:00",
        ),
        MemoryEntry(
            memory_id="card-rank-new-less-important",
            content="raw beta",
            summary="database boundary card",
            user_id="u_filter",
            memory_type=MemoryType.SEMANTIC,
            conversation_id="sess-filter",
            importance=0.40,
            tags=["database", "trace"],
            access_level="shared",
            created_at="2026-05-25 09:00:00",
        ),
        MemoryEntry(
            memory_id="card-rank-private",
            content="raw private",
            summary="database boundary card",
            user_id="u_filter",
            memory_type=MemoryType.SEMANTIC,
            conversation_id="sess-filter",
            importance=0.99,
            tags=["database", "trace"],
            access_level="private",
            created_at="2026-05-26 09:00:00",
        ),
        MemoryEntry(
            memory_id="card-rank-other-session",
            content="raw other",
            summary="database boundary card",
            user_id="u_filter",
            memory_type=MemoryType.EPISODIC,
            conversation_id="sess-other",
            importance=1.0,
            tags=["database", "trace"],
            access_level="shared",
            created_at="2026-05-26 10:00:00",
        ),
    ]
    for entry in entries:
        await repo.write_raw_and_card(_entry_to_command(entry))

    rows = await svc.search_memory_cards(
        query="database boundary",
        user_id="u_filter",
        memory_types=[MemoryType.SEMANTIC],
        access_levels=["shared"],
        tags=["trace"],
        conversation_id="sess-filter",
        limit=10,
    )

    assert [r["memory_id"] for r in rows] == [
        "card-rank-old-important",
        "card-rank-new-less-important",
    ]
    assert rows[0]["_score"] > rows[1]["_score"]


@pytest.mark.asyncio
async def test_memory_service_search_memory_defaults_to_card_shape():
    from agentmind.memory.service import MemoryService

    svc = MemoryService()
    await svc.write_memory({
        "memory_id": "svc-card-search-1",
        "content": "raw content about card-first retrieval",
        "summary": "card-first retrieval path",
        "source_agent": "codex",
        "source_task_id": "task-service-card",
        "user_id": "u_service_cards",
        "tags": ["memory", "cards"],
        "access_level": "shared",
    })

    card_rows = await svc.search_memory_cards(
        query="card-first retrieval",
        user_id="u_service_cards",
        source_agent="codex",
        tags=["cards"],
        limit=5,
    )
    default_rows = await svc.search_memory(
        query="card-first retrieval",
        user_id="u_service_cards",
        limit=5,
    )

    assert [r["memory_id"] for r in card_rows] == ["svc-card-search-1"]
    assert "card_text" in card_rows[0]
    assert card_rows[0]["raw_memory_id"] == "svc-card-search-1"
    assert card_rows[0]["_route"] == "memory_cards"
    assert [r["memory_id"] for r in default_rows] == ["svc-card-search-1"]
    assert "card_text" in default_rows[0]
    assert default_rows[0]["raw_memory_id"] == "svc-card-search-1"
    assert default_rows[0]["_route"] == "memory_cards"


@pytest.mark.asyncio
async def test_memory_card_filters_are_applied_before_limit_to_prevent_missed_hits():
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    repo = SqliteMemoryRepository()
    svc = MemoryService(repository=repo)
    for index in range(6):
        await repo.write_raw_and_card(MemoryWriteCommand(
            memory_id=f"filter-decoy-{index}",
            content="phase12 quality filter candidate",
            summary="phase12 quality decoy",
            user_id="u_filter_pushdown",
            memory_type="semantic",
            conversation_id="conv-other",
            created_at=f"2026-05-29 10:0{index}:00",
            access_level="shared",
        ))
    for index in range(2):
        await repo.write_raw_and_card(MemoryWriteCommand(
            memory_id=f"filter-target-{index}",
            content="phase12 quality filter candidate",
            summary="phase12 quality target",
            user_id="u_filter_pushdown",
            memory_type="procedural",
            conversation_id="conv-target",
            created_at=f"2026-05-28 09:0{index}:00",
            access_level="shared",
        ))

    rows = await svc.search_memory_cards(
        query="phase12 quality",
        user_id="u_filter_pushdown",
        memory_types=[MemoryType.PROCEDURAL],
        conversation_id="conv-target",
        access_levels=["shared"],
        limit=2,
    )

    assert [row["memory_id"] for row in rows] == [
        "filter-target-0",
        "filter-target-1",
    ]


@pytest.mark.asyncio
async def test_memory_service_search_memory_has_no_legacy_table_fallback():
    from agentmind.memory.service import MemoryService

    svc = MemoryService()
    conn = svc.store.connect_sync()
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual')"
            ).fetchall()
        }
    finally:
        conn.close()

    assert "memory_entries" not in tables
    rows = await svc.search_memory(
        query="unmigrated content",
        user_id="u_legacy",
        limit=5,
    )

    assert rows == []


def _fixture_cases_by_category():
    fixture_path = Path(__file__).parent / "fixtures" / "memory_retrieval_cases.yaml"
    data = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
    return {case["category"]: case for case in data["cases"]}


def _entry_to_command(entry: MemoryEntry):
    from agentmind.memory.dto import MemoryWriteCommand

    return MemoryWriteCommand(
        memory_id=entry.memory_id,
        content=entry.content,
        summary=entry.summary,
        user_id=entry.user_id,
        source_agent=entry.source_agent,
        source_task_id=entry.source_task_id,
        conversation_id=entry.conversation_id,
        tags=entry.tags,
        memory_type=entry.memory_type.value,
        importance=entry.importance,
        access_level=entry.access_level,
        content_hash=entry.content_hash,
        parent_id=entry.parent_id,
        created_at=entry.created_at,
    )


@pytest.mark.asyncio
async def test_memory_cards_search_smoke_covers_topic_date_and_agent_fixture_cases():
    from agentmind.memory.service import MemoryService

    cases = _fixture_cases_by_category()
    svc = MemoryService()

    selected = [
        cases["topic_query"],
        cases["date_query"],
        cases["agent_source"],
    ]

    for case in selected:
        seed = case["seed_memories"][0]
        memory_id = f"fixture-card-{case['category']}"
        await svc.write_memory({
            "memory_id": memory_id,
            "content": seed["content"],
            "summary": seed["content"],
            "source_agent": seed.get("agent_id", seed.get("role", "")),
            "source_task_id": case["id"],
            "user_id": seed["user_id"],
            "conversation_id": seed["session_id"],
            "tags": seed.get("tags", []),
            "created_at": seed.get("created_at", ""),
            "access_level": seed.get("access_level", "shared"),
        })

    topic_rows = await svc.search_memory_cards(
        query="MemoryService 唯一入口",
        user_id="u_eval",
        tags=["memory"],
        limit=3,
    )
    date_rows = await svc.search_memory_cards(
        query="飞书 WebSocket 重连",
        user_id="u_eval",
        time_range_start="2026-05-25",
        time_range_end="2026-05-25T23:59:59+08:00",
        limit=3,
    )
    agent_rows = await svc.search_memory_cards(
        query="数据库建议",
        user_id="u_eval",
        source_agent="codex",
        limit=3,
    )

    assert any(r["source_task_id"] == "topic-query-memory-service" for r in topic_rows)
    assert any(r["source_task_id"] == "date-filter-yesterday" for r in date_rows)
    assert any(r["source_task_id"] == "agent-source-codex" for r in agent_rows)
