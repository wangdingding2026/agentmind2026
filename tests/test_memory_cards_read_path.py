from pathlib import Path

import pytest
import yaml

from agentmind.memory.types import MemoryEntry, MemoryType, SearchQuery


@pytest.mark.asyncio
async def test_sqlite_store_search_memory_cards_reads_card_text_not_legacy_content():
    from agentmind.memory.sqlite_store import SqliteMemoryStore

    store = SqliteMemoryStore()
    await store.insert(MemoryEntry(
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
    ))

    rows = await store.search_memory_cards(SearchQuery(
        query_text="retrieval surface",
        user_id="u_cards",
        limit=5,
    ))

    assert [r["memory_id"] for r in rows] == ["card-read-1"]
    assert rows[0]["raw_memory_id"] == "card-read-1"
    assert rows[0]["card_text"].startswith("Memory cards are the retrieval surface")
    assert rows[0]["source_refs"]["source_agent"] == "codex"
    assert rows[0]["score_metadata"]["memory_type"] == "semantic"
    assert rows[0]["_route"] == "memory_cards"


@pytest.mark.asyncio
async def test_sqlite_store_search_memory_cards_filters_and_orders_results():
    from agentmind.memory.sqlite_store import SqliteMemoryStore

    store = SqliteMemoryStore()
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
    await store.batch_insert(entries)

    rows = await store.search_memory_cards(SearchQuery(
        query_text="database boundary",
        user_id="u_filter",
        memory_types=[MemoryType.SEMANTIC],
        access_levels=["shared"],
        tags=["trace"],
        conversation_id="sess-filter",
        limit=10,
    ))

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
async def test_memory_service_search_memory_falls_back_only_for_unmigrated_legacy_rows():
    import sqlite3

    from agentmind.memory.service import MemoryService
    from agentmind.storage.db import DATA_DIR

    conn = sqlite3.connect(str(DATA_DIR / "memory.db"))
    try:
        conn.execute(
            """INSERT INTO memory_entries
               (memory_id, content, summary, source_agent, source_task_id,
                created_at, access_level, tags, user_id, memory_type, conversation_id, importance)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "legacy-only-search-1",
                "legacy-only content before card migration",
                "legacy fallback summary",
                "legacy-agent",
                "legacy-task",
                "2026-05-25 10:00:00",
                "shared",
                '["legacy"]',
                "u_legacy",
                "episodic",
                "legacy-session",
                0.5,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    rows = await MemoryService().search_memory(
        query="legacy-only content",
        user_id="u_legacy",
        limit=5,
    )

    assert [r["memory_id"] for r in rows] == ["legacy-only-search-1"]
    assert rows[0]["_route"] != "memory_cards"
    assert rows[0]["content"] == "legacy-only content before card migration"


def _fixture_cases_by_category():
    fixture_path = Path(__file__).parent / "fixtures" / "memory_retrieval_cases.yaml"
    data = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
    return {case["category"]: case for case in data["cases"]}


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
