import pytest


@pytest.mark.asyncio
async def test_write_memory_promotes_high_confidence_llm_knowledge(tmp_path, monkeypatch):
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    async def fake_core_llm_chat(messages, temperature=0.1):
        return """
        {
          "should_promote": true,
          "knowledge_type": "team_decision",
          "title": "默认向量检索使用纯 SQLite 保底",
          "content": "AgentMind v1.0.0 默认不强制安装 sqlite-vec，网络受限环境使用纯 SQLite 进行向量检索保底。",
          "confidence": 0.91,
          "evidence": "默认不强制安装 sqlite-vec"
        }
        """

    monkeypatch.setattr(
        "agentmind.memory.components.knowledge_extractor.core_llm_chat",
        fake_core_llm_chat,
    )

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    count = await MemoryService(repository=repo).write_memory({
        "memory_id": "knowledge-source-1",
        "content": "本次结论：默认不强制安装 sqlite-vec，网络受限环境使用纯 SQLite 保底检索。",
        "summary": "默认向量检索使用纯 SQLite 保底",
        "user_id": "u_knowledge",
        "source_agent": "codex",
        "source_task_id": "trace-knowledge-1",
        "memory_type": "semantic",
    })
    rows = await repo.search_knowledge(
        query="SQLite 保底",
        user_id="u_knowledge",
        statuses=["active"],
        limit=5,
    )

    assert count == 1
    assert [row["knowledge_type"] for row in rows] == ["team_decision"]
    assert rows[0]["source_memory_id"] == "knowledge-source-1"
    assert rows[0]["status"] == "active"


@pytest.mark.asyncio
async def test_write_memory_promotes_low_confidence_knowledge_as_pending(tmp_path, monkeypatch):
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    async def fake_core_llm_chat(messages, temperature=0.1):
        return """
        {
          "should_promote": true,
          "knowledge_type": "procedure",
          "title": "本地提交前先跑全量测试",
          "content": "修复完成后先运行全量测试，再做本地提交。",
          "confidence": 0.72,
          "evidence": "修复完成后先运行全量测试"
        }
        """

    monkeypatch.setattr(
        "agentmind.memory.components.knowledge_extractor.core_llm_chat",
        fake_core_llm_chat,
    )

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    await MemoryService(repository=repo).write_memory({
        "memory_id": "knowledge-source-2",
        "content": "修复完成后先运行全量测试，再做本地提交。",
        "summary": "本地提交前先跑全量测试",
        "user_id": "u_knowledge_pending",
        "source_agent": "codex",
        "source_task_id": "trace-knowledge-2",
        "memory_type": "procedural",
    })
    active_rows = await repo.search_knowledge(
        query="全量测试",
        user_id="u_knowledge_pending",
        statuses=["active"],
        limit=5,
    )
    pending_rows = await repo.search_knowledge(
        query="全量测试",
        user_id="u_knowledge_pending",
        statuses=["pending"],
        limit=5,
    )

    assert active_rows == []
    assert [row["status"] for row in pending_rows] == ["pending"]


@pytest.mark.asyncio
async def test_write_memory_keeps_card_when_llm_knowledge_output_is_invalid(tmp_path, monkeypatch):
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    async def fake_core_llm_chat(messages, temperature=0.1):
        return "not json"

    monkeypatch.setattr(
        "agentmind.memory.components.knowledge_extractor.core_llm_chat",
        fake_core_llm_chat,
    )

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    count = await MemoryService(repository=repo).write_memory({
        "memory_id": "knowledge-invalid",
        "content": "这条普通记忆不能因为知识抽取失败而丢失。",
        "summary": "普通记忆保留",
        "user_id": "u_knowledge_invalid",
        "memory_type": "semantic",
    })
    rows = await repo.search_knowledge(
        query="普通记忆",
        user_id="u_knowledge_invalid",
        statuses=["active", "pending"],
        limit=5,
    )

    assert count == 1
    assert await repo.get_card("knowledge-invalid") is not None
    assert rows == []


@pytest.mark.asyncio
async def test_write_memory_does_not_promote_when_llm_declines(tmp_path, monkeypatch):
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    async def fake_core_llm_chat(messages, temperature=0.1):
        return '{"should_promote": false, "reason": "一次性过程信息"}'

    monkeypatch.setattr(
        "agentmind.memory.components.knowledge_extractor.core_llm_chat",
        fake_core_llm_chat,
    )

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    await MemoryService(repository=repo).write_memory({
        "memory_id": "knowledge-decline",
        "content": "这只是一次临时过程讨论，不应进入团队知识库。",
        "summary": "临时讨论",
        "user_id": "u_knowledge_decline",
        "memory_type": "episodic",
    })
    rows = await repo.search_knowledge(
        query="临时讨论",
        user_id="u_knowledge_decline",
        statuses=["active", "pending"],
        limit=5,
    )

    assert rows == []


@pytest.mark.asyncio
async def test_existing_memory_is_not_backfilled_into_knowledge_items(tmp_path, monkeypatch):
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    await repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="old-before-knowledge",
        content="旧结论：这条旧数据不应该被新流程回填。",
        summary="旧数据",
        user_id="u_no_backfill",
        access_level="shared",
    ))

    async def fake_core_llm_chat(messages, temperature=0.1):
        return """
        {
          "should_promote": true,
          "knowledge_type": "task_conclusion",
          "title": "新流程只处理新知识",
          "content": "知识库流程上线后只处理新写入的记忆，不回填旧数据。",
          "confidence": 0.92,
          "evidence": "只处理新写入的记忆"
        }
        """

    monkeypatch.setattr(
        "agentmind.memory.components.knowledge_extractor.core_llm_chat",
        fake_core_llm_chat,
    )

    await MemoryService(repository=repo).write_memory({
        "memory_id": "new-after-knowledge",
        "content": "知识库流程上线后只处理新写入的记忆，不回填旧数据。",
        "summary": "新流程只处理新知识",
        "user_id": "u_no_backfill",
        "memory_type": "semantic",
    })
    rows = await repo.search_knowledge(
        query="新流程",
        user_id="u_no_backfill",
        statuses=["active"],
        limit=5,
    )

    assert [row["source_memory_id"] for row in rows] == ["new-after-knowledge"]


@pytest.mark.asyncio
async def test_retrieve_context_injects_active_team_knowledge_with_existing_memory(tmp_path):
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    svc = MemoryService(repository=repo)
    await repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="ordinary-memory",
        content="普通记忆：SQLite fallback 的实现细节。",
        summary="SQLite fallback 普通记忆",
        user_id="u_knowledge_ctx",
        access_level="shared",
    ))
    await repo.write_knowledge_item({
        "knowledge_id": "kb-ctx-1",
        "user_id": "u_knowledge_ctx",
        "knowledge_type": "team_decision",
        "title": "默认向量检索使用纯 SQLite 保底",
        "content": "AgentMind v1.0.0 默认不强制安装 sqlite-vec，网络受限环境使用纯 SQLite 保底检索。",
        "source_memory_id": "ordinary-memory",
        "source_agent": "codex",
        "source_task_id": "trace-kb",
        "confidence": 0.95,
        "status": "active",
        "evidence": "默认不强制安装 sqlite-vec",
    })

    ctx = await svc.retrieve_context(
        "SQLite 保底",
        user_id="u_knowledge_ctx",
        settings={"embedding": {"enabled": False}, "memory": {"context_max_bytes": 4096}},
    )

    assert "knowledge_items" in ctx.steps
    assert "[团队知识库]" in ctx.assembled_context
    assert "[team_decision] 默认向量检索使用纯 SQLite 保底" in ctx.assembled_context
    assert ctx.assembled_context.index("[团队知识库]") < ctx.assembled_context.index("[相关记忆]")
