import pytest


@pytest.mark.asyncio
async def test_retrieve_context_does_not_require_v4_retrieval_flag(tmp_path):
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    svc = MemoryService(repository=repo)
    svc.add_to_working_memory("u1", "user", "当前会话提到部署端口 8765")
    svc.add_to_working_memory("u1", "assistant", "我会记住端口 8765")
    await svc.write_memory({
        "memory_id": "ctx-card-1",
        "content": "历史部署记录说明 nginx timeout 需要调大。",
        "summary": "nginx timeout 调整",
        "user_id": "u1",
        "source_agent": "codex",
        "source_task_id": "trace-ctx",
        "tags": ["deploy"],
        "memory_type": "semantic",
    })

    ctx = await svc.retrieve_context(
        "部署端口和 timeout",
        user_id="u1",
        settings={"memory": {"working_memory_rounds": 3, "context_max_bytes": 4096}},
    )
    result = await svc.retrieve(
        "部署端口和 timeout",
        user_id="u1",
        settings={"memory": {"working_memory_rounds": 3, "context_max_bytes": 4096}},
    )

    assert "当前会话提到部署端口 8765" in ctx.assembled_context
    assert "nginx timeout 调整" in ctx.assembled_context
    assert ctx.working_memory
    assert ctx.recall_items
    assert "nginx timeout 调整" in result["assembled_context"]


@pytest.mark.asyncio
async def test_memory_retriever_returns_memory_context_without_v4_sentinel(monkeypatch):
    from agentmind.memory.dto import MemoryContext
    from agentmind.routing.middleware import memory_retriever

    class FakeMemoryService:
        async def retrieve_context(self, message, user_id="", settings=None, limit=5):
            return MemoryContext(
                assembled_context="[相关记忆]\n部署端口 8765",
                recall_items=[{
                    "memory_id": "card-1",
                    "content": "部署端口 8765",
                    "_route": "memory_cards",
                }],
                steps=["memory_cards"],
            )

        async def expand_result(self, result_index, user_id, result_set_id=""):
            return None

        async def more_results(self, user_id, result_set_id="", page_size=5):
            return None

    monkeypatch.setattr(memory_retriever, "MemoryService", FakeMemoryService)

    ctx = await memory_retriever.MemoryRetriever().retrieve("部署端口", "u1", limit=5)

    assert isinstance(ctx, MemoryContext)
    assert ctx.recall_items
    assert all(not item.get("_v4_assembled") for item in ctx.recall_items)


def test_prompt_envelope_accepts_memory_context():
    from agentmind.memory.dto import MemoryContext
    from agentmind.routing.envelope import PromptEnvelope

    result = PromptEnvelope.build(
        "现在怎么处理？",
        MemoryContext(assembled_context="[相关记忆]\n部署端口 8765"),
    )

    assert "部署端口 8765" in result
    assert "当前指令：现在怎么处理？" in result


@pytest.mark.asyncio
async def test_retrieve_context_creates_result_set_after_merge_for_recent_only_hit(tmp_path):
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    svc = MemoryService(repository=repo)
    await repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="recent-only-card",
        content="只有最近记忆会召回的完整原文。",
        summary="最近记忆摘要",
        user_id="u_recent_only",
        access_level="shared",
    ))

    ctx = await svc.retrieve_context(
        "完全不匹配关键词",
        user_id="u_recent_only",
        settings={"memory": {"retrieval_max_candidates": 5, "context_max_bytes": 4096}},
    )
    expanded = await svc.expand_result(
        1,
        user_id="u_recent_only",
        result_set_id=ctx.result_set_id,
    )

    assert ctx.result_set_id.startswith("rs-")
    assert ctx.recall_items[0]["memory_id"] == "recent-only-card"
    assert expanded["memory_id"] == "recent-only-card"
    assert expanded["content"] == "只有最近记忆会召回的完整原文。"


@pytest.mark.asyncio
async def test_retrieve_context_orders_merged_rows_by_score_before_assembly():
    from agentmind.memory.service import MemoryService

    repo = FakeRetrievalRepository(
        keyword_rows=[_card("keyword-low", "keyword result", 0.2)],
        relation_rows=[_card("relation-high", "relation result", 2.0)],
        recent_rows=[_card("recent-mid", "recent result", 0.8)],
    )
    ctx = await MemoryService(repository=repo).retrieve_context(
        "ranking query",
        user_id="u_rank",
        settings={"memory": {"retrieval_max_candidates": 3, "context_max_bytes": 4096}},
        limit=3,
    )

    assert [row["memory_id"] for row in ctx.recall_items] == [
        "relation-high",
        "recent-mid",
        "keyword-low",
    ]
    assert repo.result_set_memory_ids == [
        "relation-high",
        "recent-mid",
        "keyword-low",
    ]


@pytest.mark.asyncio
async def test_retrieve_context_uses_reranker_when_enabled(monkeypatch):
    from agentmind.memory.service import MemoryService

    calls = []

    class FakeReranker:
        async def rerank(self, query, candidates, top_k=10):
            calls.append((query, [item.entry.memory_id for item in candidates], top_k))
            return list(reversed(candidates))

    monkeypatch.setattr("agentmind.memory.pipeline.reranker.Reranker", FakeReranker)

    repo = FakeRetrievalRepository(
        keyword_rows=[
            _card("first-by-score", "first before reranker", 2.0),
            _card("second-by-score", "second before reranker", 1.0),
        ],
    )
    ctx = await MemoryService(repository=repo).retrieve_context(
        "rerank query",
        user_id="u_rerank",
        settings={
            "memory": {
                "retrieval_max_candidates": 2,
                "context_max_bytes": 4096,
                "reranker_enabled": True,
            }
        },
        limit=2,
    )

    assert calls == [("rerank query", ["first-by-score", "second-by-score"], 2)]
    assert [row["memory_id"] for row in ctx.recall_items] == [
        "second-by-score",
        "first-by-score",
    ]
    assert repo.result_set_memory_ids == [
        "second-by-score",
        "first-by-score",
    ]


class FakeRetrievalRepository:
    def __init__(self, keyword_rows=None, relation_rows=None, recent_rows=None):
        self.keyword_rows = keyword_rows or []
        self.relation_rows = relation_rows or []
        self.recent_rows = recent_rows or []
        self.result_set_memory_ids = []

    async def read_core_memory(self, user_id):
        return ""

    def get_working_memory_sync(self, user_id, limit=3):
        return []

    def get_active_conversation_id_sync(self, user_id):
        return ""

    async def search_cards(self, **kwargs):
        return self.keyword_rows

    async def get_recent_cards(self, **kwargs):
        return self.recent_rows

    async def related_cards_for_query(self, **kwargs):
        return self.relation_rows

    async def get_raw(self, raw_memory_id, user_id=""):
        return None

    async def create_result_set(self, user_id, query_text, items, metadata=None):
        self.result_set_memory_ids = [item["memory_id"] for item in items]
        return "rs-rank"


def _card(memory_id: str, text: str, score: float) -> dict:
    return {
        "memory_id": memory_id,
        "raw_memory_id": memory_id,
        "summary": text,
        "card_text": text,
        "content": text,
        "user_id": "u_rank",
        "source_agent": "codex",
        "source_task_id": "rank-test",
        "tags": [],
        "access_level": "shared",
        "memory_type": "semantic",
        "created_at": "2026-05-29 10:00:00",
        "score_metadata": {},
        "_score": score,
        "_route": "memory_cards",
    }
