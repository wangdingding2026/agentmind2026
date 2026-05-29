import pytest


@pytest.mark.asyncio
async def test_memory_writer_uses_memory_service_for_task_memory(monkeypatch):
    from agentmind.routing.side_effects.memory_writer import MemoryWriter

    writes = []

    async def skip_extract_facts(*args, **kwargs):
        return None

    class FakeMemoryService:
        def add_to_working_memory(self, user_id, role, content):
            pass

        async def write_memory(self, entry, generate_embedding=True, user_id=""):
            writes.append((entry, user_id))
            return 1

    monkeypatch.setattr(
        "agentmind.routing.side_effects.memory_writer.MemoryService",
        FakeMemoryService,
    )
    monkeypatch.setattr(MemoryWriter, "_extract_facts", staticmethod(skip_extract_facts))

    await MemoryWriter.write_task("tr-1", "agent-a", "hello", "world", user_id="u1")

    assert writes
    assert writes[0][0]["memory_id"] == "task-tr-1"
    assert writes[0][1] == "u1"


@pytest.mark.asyncio
async def test_memory_retriever_uses_memory_service_retrieve_context(monkeypatch):
    from agentmind.memory.dto import MemoryContext
    from agentmind.routing.middleware.memory_retriever import MemoryRetriever

    calls = []

    class FakeMemoryService:
        async def retrieve_context(self, message, user_id="", settings=None, limit=5):
            calls.append((message, user_id, limit))
            return MemoryContext(
                assembled_context="context",
                recall_items=[{"memory_id": "m-1", "content": message}],
            )

        async def expand_result(self, result_index, user_id, result_set_id=""):
            return None

        async def more_results(self, user_id, result_set_id="", page_size=5):
            return None

    monkeypatch.setattr(
        "agentmind.routing.middleware.memory_retriever.MemoryService",
        FakeMemoryService,
    )

    ctx = await MemoryRetriever().retrieve("hello world", "u1", limit=2)

    assert isinstance(ctx, MemoryContext)
    assert ctx.recall_items
    assert calls == [("hello world", "u1", 2)]


@pytest.mark.asyncio
async def test_memory_retriever_routes_expand_followup_to_result_set(monkeypatch):
    from agentmind.routing.middleware.memory_retriever import MemoryRetriever

    calls = []

    class FakeMemoryService:
        async def expand_result(self, result_index, user_id, result_set_id=""):
            calls.append(("expand", result_index, user_id, result_set_id))
            return {
                "memory_id": "expanded-card",
                "content": "expanded raw content",
                "_route": "result_set_expand",
            }

    monkeypatch.setattr(
        "agentmind.routing.middleware.memory_retriever.MemoryService",
        FakeMemoryService,
    )

    rows = await MemoryRetriever().retrieve("展开第 2 条", "u1", limit=2)

    assert rows == [{
        "memory_id": "expanded-card",
        "content": "expanded raw content",
        "_route": "result_set_expand",
    }]
    assert calls == [("expand", 2, "u1", "")]


@pytest.mark.asyncio
async def test_memory_retriever_routes_more_followup_to_result_set(monkeypatch):
    from agentmind.routing.middleware.memory_retriever import MemoryRetriever

    calls = []

    class FakeMemoryService:
        async def more_results(self, user_id, result_set_id="", page_size=5):
            calls.append(("more", user_id, result_set_id, page_size))
            return {
                "items": [
                    {"memory_id": "more-1", "content": "more card 1"},
                    {"memory_id": "more-2", "content": "more card 2"},
                ],
                "_route": "result_set_more",
            }

    monkeypatch.setattr(
        "agentmind.routing.middleware.memory_retriever.MemoryService",
        FakeMemoryService,
    )

    rows = await MemoryRetriever().retrieve("还有别的吗？", "u1", limit=2)

    assert [r["memory_id"] for r in rows] == ["more-1", "more-2"]
    assert all(r["_route"] == "result_set_more" for r in rows)
    assert calls == [("more", "u1", "", 2)]
