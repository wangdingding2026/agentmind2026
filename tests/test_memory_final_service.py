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
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()

    rows = await repo.search_cards(query="8765", user_id="u1")

    assert count == 1
    assert rows
    assert rows[0]["memory_id"] == "task-1"
    assert "memory_entries" not in tables


@pytest.mark.asyncio
async def test_write_memory_dedup_reports_zero_and_does_not_expose_missing_new_id(tmp_path):
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    svc = MemoryService(repository=repo)
    first_count = await svc.write_memory({
        "memory_id": "dedup-original",
        "content": "相同事实：部署端口是 8765。",
        "summary": "部署端口 8765",
        "user_id": "u_dedup",
        "memory_type": "semantic",
    })
    # 内容+摘要完全相同的重复写入 → 应被去重
    second_count = await svc.write_memory({
        "memory_id": "dedup-new-id",
        "content": "相同事实：部署端口是 8765。",
        "summary": "部署端口 8765",
        "user_id": "u_dedup",
        "memory_type": "semantic",
    })
    # 内容相同但摘要不同 → 不应被去重（不同记忆）
    third_count = await svc.write_memory({
        "memory_id": "dedup-diff-summary",
        "content": "相同事实：部署端口是 8765。",
        "summary": "重复部署端口 8765",
        "user_id": "u_dedup",
        "memory_type": "semantic",
    })

    rows = await svc.search_memory("部署端口 8765", user_id="u_dedup", limit=10)

    assert first_count == 1
    assert second_count == 0, "完全相同的 content+summary 应被去重"
    assert third_count == 1, "相同 content 但不同 summary 不应被去重"
    assert await repo.get_card("dedup-new-id") is None
    assert await repo.get_card("dedup-diff-summary") is not None
    assert [row["memory_id"] for row in rows] == [
        "dedup-diff-summary", "dedup-original",
    ]


@pytest.mark.asyncio
async def test_write_memory_runs_relation_enrichment_before_return(tmp_path, monkeypatch):
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    calls = []

    class FakeRelationExtractor:
        async def extract(self, memory_id, content):
            calls.append((memory_id, content))
            return [(memory_id, "references", "检索策略", "", 0.8)]

    monkeypatch.setattr(
        "agentmind.memory.components.relation_extractor.RelationExtractor",
        FakeRelationExtractor,
    )

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    svc = MemoryService(repository=repo)
    count = await svc.write_memory({
        "memory_id": "enrich-sync-1",
        "content": "参考：检索策略",
        "summary": "检索策略参考",
        "user_id": "u_enrich",
        "memory_type": "semantic",
    })
    related = await repo.related_cards_for_query("检索策略", "u_enrich", limit=5)

    assert count == 1
    assert calls == [("enrich-sync-1", "参考：检索策略")]
    assert [row["memory_id"] for row in related] == ["enrich-sync-1"]


@pytest.mark.asyncio
async def test_write_memory_keeps_raw_card_when_relation_enrichment_fails(tmp_path, monkeypatch):
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    calls = []

    class FailingRelationExtractor:
        async def extract(self, memory_id, content):
            calls.append(memory_id)
            raise RuntimeError("relation extractor unavailable")

    monkeypatch.setattr(
        "agentmind.memory.components.relation_extractor.RelationExtractor",
        FailingRelationExtractor,
    )

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    svc = MemoryService(repository=repo)
    count = await svc.write_memory({
        "memory_id": "enrich-fail-1",
        "content": "参考：失败也要保留主记忆",
        "summary": "富化失败主写入保留",
        "user_id": "u_enrich_fail",
        "memory_type": "semantic",
    })

    assert count == 1
    assert calls == ["enrich-fail-1"]
    assert await repo.get_card("enrich-fail-1") is not None
    assert await repo.get_raw("enrich-fail-1", user_id="u_enrich_fail") is not None


@pytest.mark.asyncio
async def test_write_memory_persists_vector_when_embedding_is_available(tmp_path, monkeypatch):
    """v1.0.0 写入记忆时应能形成真实向量索引；失败时仍由实现自行降级。"""
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    class FakeEmbeddingProvider:
        async def generate_embedding(self, content):
            return [1.0, 0.0]

    monkeypatch.setattr(
        "agentmind.memory.pipeline.write_pipeline.MemoryEmbeddingProvider",
        FakeEmbeddingProvider,
    )

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    count = await MemoryService(repository=repo).write_memory({
        "memory_id": "vector-runtime-1",
        "content": "部署端口 8765 需要保留给 AgentMind 服务。",
        "summary": "部署端口 8765",
        "user_id": "u_vector_runtime",
        "memory_type": "semantic",
    })
    rows = await repo.search_vector(
        query_embedding=[1.0, 0.0],
        user_id="u_vector_runtime",
        limit=5,
    )

    assert count == 1
    assert await repo.get_card("vector-runtime-1") is not None
    assert [row["memory_id"] for row in rows] == ["vector-runtime-1"]
