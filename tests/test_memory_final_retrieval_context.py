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
