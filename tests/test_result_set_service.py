import pytest

from agentmind.memory.types import MemoryEntry


@pytest.mark.asyncio
async def test_result_set_service_creates_set_and_expands_raw_memory():
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.services.result_set_service import ResultSetService

    repo = SqliteMemoryRepository()
    await _write_entries(repo, [
        MemoryEntry(
            memory_id="rs-card-1",
            content="raw source one",
            summary="card one",
            user_id="u_rs",
            tags=["result-set"],
        ),
        MemoryEntry(
            memory_id="rs-card-2",
            content="raw source two with full details",
            summary="card two",
            user_id="u_rs",
            tags=["result-set"],
        ),
    ])

    svc = ResultSetService(repository=repo)
    result_set_id = await svc.create_result_set(
        user_id="u_rs",
        query_text="result set query",
        memory_ids=["rs-card-1", "rs-card-2"],
        metadata={"route": "memory_cards"},
    )

    expanded = await svc.expand_result(result_set_id, 2, user_id="u_rs")

    assert result_set_id.startswith("rs-")
    assert expanded["result_set_id"] == result_set_id
    assert expanded["result_index"] == 2
    assert expanded["memory_id"] == "rs-card-2"
    assert expanded["raw_memory_id"] == "rs-card-2"
    assert expanded["content"] == "raw source two with full details"
    assert expanded["card"]["summary"] == "card two"


@pytest.mark.asyncio
async def test_result_set_service_next_page_advances_cursor():
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.services.result_set_service import ResultSetService

    repo = SqliteMemoryRepository()
    await _write_entries(repo, [
        MemoryEntry(memory_id=f"rs-page-{i}", content=f"raw {i}", summary=f"card {i}", user_id="u_rs")
        for i in range(1, 6)
    ])

    svc = ResultSetService(repository=repo)
    result_set_id = await svc.create_result_set(
        user_id="u_rs",
        query_text="paged result set",
        memory_ids=[f"rs-page-{i}" for i in range(1, 6)],
    )

    first = await svc.next_page(result_set_id, user_id="u_rs", page_size=2)
    second = await svc.next_page(result_set_id, user_id="u_rs", page_size=2)
    third = await svc.next_page(result_set_id, user_id="u_rs", page_size=2)

    assert [item["memory_id"] for item in first["items"]] == ["rs-page-1", "rs-page-2"]
    assert first["next_cursor"] == 2
    assert first["has_more"] is True
    assert [item["memory_id"] for item in second["items"]] == ["rs-page-3", "rs-page-4"]
    assert second["next_cursor"] == 4
    assert second["has_more"] is True
    assert [item["memory_id"] for item in third["items"]] == ["rs-page-5"]
    assert third["next_cursor"] == 5
    assert third["has_more"] is False


@pytest.mark.asyncio
async def test_memory_service_card_search_attaches_result_set_metadata():
    from agentmind.memory.service import MemoryService

    svc = MemoryService()
    await svc.write_memory({
        "memory_id": "svc-rs-1",
        "content": "result set service alpha",
        "summary": "result set alpha",
        "user_id": "u_svc_rs",
        "tags": ["result-set"],
    })
    await svc.write_memory({
        "memory_id": "svc-rs-2",
        "content": "result set service beta",
        "summary": "result set beta",
        "user_id": "u_svc_rs",
        "tags": ["result-set"],
    })

    rows = await svc.search_memory(
        query="result set service",
        user_id="u_svc_rs",
        tags=["result-set"],
        limit=5,
    )

    assert len(rows) == 2
    assert rows[0]["_result_set_id"].startswith("rs-")
    assert rows[0]["_result_set_id"] == rows[1]["_result_set_id"]
    assert [r["_result_index"] for r in rows] == [1, 2]


@pytest.mark.asyncio
async def test_memory_service_expands_and_pages_latest_result_set():
    from agentmind.memory.service import MemoryService

    svc = MemoryService()
    for index in range(1, 4):
        await svc.write_memory({
            "memory_id": f"svc-follow-{index}",
            "content": f"full raw follow-up content {index}",
            "summary": f"follow-up card {index}",
            "user_id": "u_follow",
            "tags": ["follow-up"],
        })

    rows = await svc.search_memory(
        query="follow-up",
        user_id="u_follow",
        tags=["follow-up"],
        limit=3,
    )

    expanded = await svc.expand_result(result_index=2, user_id="u_follow")
    more = await svc.more_results(user_id="u_follow", page_size=2)

    assert expanded["result_set_id"] == rows[0]["_result_set_id"]
    assert expanded["result_index"] == 2
    assert expanded["content"].startswith("full raw follow-up content")
    assert expanded["card"]["memory_id"] == rows[1]["memory_id"]
    assert [item["_result_index"] for item in more["items"]] == [1, 2]
    assert more["has_more"] is True


async def _write_entries(repo, entries: list[MemoryEntry]) -> None:
    from agentmind.memory.dto import MemoryWriteCommand

    for entry in entries:
        await repo.write_raw_and_card(MemoryWriteCommand(
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
            created_at=entry.created_at,
        ))
