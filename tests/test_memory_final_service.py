import pytest


class FakeRepository:
    def __init__(self, cards=None):
        self.cards = cards or []

    async def search_cards(self, **kwargs):
        return self.cards

    async def create_result_set(self, user_id, query_text, items, metadata=None):
        return "rs-test"


@pytest.mark.asyncio
async def test_search_memory_returns_card_rows_with_compatible_fields():
    from agentmind.memory.service import MemoryService

    class FakeStore:
        async def search_memory_cards(self, query):
            return [{
                "memory_id": "card-1",
                "raw_memory_id": "raw-1",
                "summary": "登录超时修复",
                "card_text": "登录超时通过 ttl 7200 修复",
                "source_agent": "codex",
                "source_task_id": "trace-1",
                "tags": ["login"],
                "created_at": "2026-05-29 00:00:00",
                "score_metadata": {},
            }]

        async def search(self, query):
            raise AssertionError("legacy search must not be called")

    rows = await MemoryService(
        store=FakeStore(),
        repository=FakeRepository([{
            "memory_id": "card-1",
            "raw_memory_id": "raw-1",
            "summary": "登录超时修复",
            "card_text": "登录超时通过 ttl 7200 修复",
            "source_agent": "codex",
            "source_task_id": "trace-1",
            "tags": ["login"],
            "created_at": "2026-05-29 00:00:00",
            "score_metadata": {},
        }]),
    ).search_memory("登录超时", user_id="u1")

    assert rows[0]["memory_id"] == "card-1"
    assert rows[0]["raw_memory_id"] == "raw-1"
    assert rows[0]["content"] == "登录超时通过 ttl 7200 修复"
    assert rows[0]["summary"] == "登录超时修复"
    assert rows[0]["source_agent"] == "codex"
    assert rows[0]["source_task_id"] == "trace-1"
    assert rows[0]["tags"] == ["login"]
    assert rows[0]["created_at"] == "2026-05-29 00:00:00"
    assert rows[0]["_route"] == "memory_cards"
    assert rows[0]["_result_set_id"] == "rs-test"


@pytest.mark.asyncio
async def test_search_memory_does_not_fallback_to_legacy_entries_when_cards_empty():
    from agentmind.memory.service import MemoryService

    class FakeStore:
        async def search_memory_cards(self, query):
            return []

        async def search(self, query):
            raise AssertionError("legacy search must not be called")

    rows = await MemoryService(
        store=FakeStore(), repository=FakeRepository()
    ).search_memory("没有卡片", user_id="u1")

    assert rows == []


@pytest.mark.asyncio
async def test_write_memory_creates_raw_and_card_without_legacy_entry(tmp_path):
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    svc = MemoryService(repository=repo)

    count = await svc.write_memory({
        "memory_id": "task-1",
        "content": "部署端口是 8765。",
        "summary": "部署端口 8765",
        "user_id": "u1",
        "source_agent": "codex",
        "source_task_id": "trace-1",
    })

    conn = repo.connect_sync()
    try:
        legacy_count = conn.execute(
            "SELECT COUNT(*) FROM memory_entries WHERE memory_id=?",
            ("task-1",),
        ).fetchone()[0]
    finally:
        conn.close()

    rows = await repo.search_cards(query="8765", user_id="u1")

    assert count == 1
    assert rows
    assert rows[0]["memory_id"] == "task-1"
    assert legacy_count == 0
