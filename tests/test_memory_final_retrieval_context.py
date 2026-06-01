import pytest


def _local_today_dates():
    from datetime import datetime, timedelta, timezone

    from agentmind.services.time_service import to_local

    today = to_local(datetime.now(timezone.utc)).date()
    yesterday = today - timedelta(days=1)
    return {
        "old": yesterday.strftime("%Y-%m-%d"),
        "today": today.strftime("%Y-%m-%d"),
    }


def test_conversation_history_parser_detects_today_query():
    from datetime import datetime, timezone

    from agentmind.memory.pipeline.query_understanding import parse_conversation_history_query

    parsed = parse_conversation_history_query(
        "今天我们聊过什么内容吗",
        now=datetime(2026, 5, 29, 10, 12, tzinfo=timezone.utc),
    )

    assert parsed is not None
    assert parsed.intent == "conversation_history"
    assert parsed.time_range_start == "2026-05-28 16:00:00"
    assert parsed.time_range_end == "2026-05-29 15:59:59"
    assert parsed.current_session is False


def test_conversation_history_parser_detects_current_session_query():
    from agentmind.memory.pipeline.query_understanding import parse_conversation_history_query

    parsed = parse_conversation_history_query("当前session里聊过什么")

    assert parsed is not None
    assert parsed.current_session is True


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
async def test_self_reply_formats_memory_dates_in_local_timezone():
    """历史查询日期本地化已由 ConversationHistoryExecutor 处理。"""
    from agentmind.routing.context import RequestIdentity, RoutingContext, RoutingDecision
    from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor
    from agentmind.routing.semantic_intent import SemanticIntent, SemanticIntentType

    intent = SemanticIntent(
        intent=SemanticIntentType.CONVERSATION_HISTORY,
        confidence=0.92,
        time_scope="today",
        requested_format="qa_summary",
    )
    ctx = RoutingContext(
        identity=RequestIdentity(user_id="u_local_time"),
        raw_message="今天我们聊过什么内容吗",
        memories=[{
            "memory_id": "m1",
            "content": "你是谁",
            "summary": "[agentmind] 我是 AgentMind",
            "source_agent": "agentmind",
            "created_at": "2026-05-28 16:30:00",
        }],
        semantic_intent=intent,
    )

    class FakeMemoryService:
        async def read_conversation_turns(self, **kw):
            return [
                {
                    "memory_id": "m1",
                    "created_at": "2026-05-28 16:30:00",
                    "conversation_id": "",
                    "source_agent": "agentmind",
                    "source_kind": "conversation_turn",
                    "question": "你是谁",
                    "answer": "我是 AgentMind",
                },
            ]

    from unittest.mock import patch
    with patch("agentmind.memory.service.MemoryService", FakeMemoryService):
        reply = await ConversationHistoryExecutor(agent_registry=None).build_reply(
            RoutingDecision(agent_id="agentmind", context=ctx, semantic_intent=intent),
            "u_local_time",
        )

    assert "2026-05-29" in reply
    assert "2026-05-28" not in reply


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
async def test_today_conversation_history_query_uses_date_scope_not_keyword_rank(tmp_path):
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    dates = _local_today_dates()
    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    svc = MemoryService(repository=repo)
    await repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="old-keyword-today",
        content="今天日期是多少",
        summary=f"[hermes] 今天是 {dates['old']}",
        user_id="u_today_history",
        source_agent="hermes",
        source_kind="conversation_turn",
        created_at=f"{dates['old']} 08:45:22",
    ))
    await repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="real-today-self",
        content="你是谁",
        summary="[agentmind] 我是 AgentMind",
        user_id="u_today_history",
        source_agent="agentmind",
        source_kind="conversation_turn",
        created_at=f"{dates['today']} 09:00:00",
    ))
    await repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="real-today-codex",
        content="@codex 你可以写代码吗？",
        summary="[codex] 可以。我是 Codex",
        user_id="u_today_history",
        source_agent="codex",
        source_kind="conversation_turn",
        created_at=f"{dates['today']} 09:08:00",
    ))

    ctx = await svc.retrieve_context(
        "今天我们聊过什么内容吗",
        user_id="u_today_history",
        settings={"timezone": "Asia/Shanghai", "memory": {"context_max_bytes": 4096}},
    )

    assert ctx.steps[0] == "conversation_history"
    assert [row["memory_id"] for row in ctx.recall_items] == [
        "real-today-codex",
        "real-today-self",
    ]
    assert all(row["created_at"].startswith(dates["today"]) for row in ctx.recall_items)


@pytest.mark.asyncio
async def test_new_session_keeps_today_persistent_conversation_history(tmp_path):
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    dates = _local_today_dates()
    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    svc = MemoryService(repository=repo)
    await svc.write_memory({
        "memory_id": "task-self-before-new",
        "content": "你是谁",
        "summary": "[agentmind] 我是 AgentMind",
        "user_id": "u_new_history",
        "source_agent": "agentmind",
        "source_kind": "conversation_turn",
        "created_at": f"{dates['today']} 09:00:00",
    })
    await svc.write_memory({
        "memory_id": "task-codex-before-new",
        "content": "@codex 你可以写代码吗？",
        "summary": "[codex] 可以。我是 Codex",
        "user_id": "u_new_history",
        "source_agent": "codex",
        "source_kind": "conversation_turn",
        "created_at": f"{dates['today']} 09:08:00",
    })
    svc.add_to_working_memory("u_new_history", "user", "你是谁")
    svc.add_to_working_memory("u_new_history", "assistant", "我是 AgentMind")

    await svc.new_session("u_new_history")

    ctx = await svc.retrieve_context(
        "今天我们聊过什么内容吗",
        user_id="u_new_history",
        settings={"timezone": "Asia/Shanghai", "memory": {"context_max_bytes": 4096}},
    )

    assert svc.get_working_memory("u_new_history") == []
    assert [item["memory_id"] for item in ctx.recall_items] == [
        "task-codex-before-new",
        "task-self-before-new",
    ]


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
async def test_retrieve_context_orders_equal_score_recent_rows_newest_first(tmp_path):
    from agentmind.memory.dto import MemoryWriteCommand
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    svc = MemoryService(repository=repo)
    await repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="same-day-old",
        content="旧的无关键词记录。",
        summary="旧记录",
        user_id="u_recent_tie",
        access_level="shared",
        importance=0.5,
        created_at="2026-05-29 09:00:00",
    ))
    await repo.write_raw_and_card(MemoryWriteCommand(
        memory_id="same-day-new",
        content="新的无关键词记录。",
        summary="新记录",
        user_id="u_recent_tie",
        access_level="shared",
        importance=0.5,
        created_at="2026-05-29 18:00:00",
    ))

    ctx = await svc.retrieve_context(
        "完全不匹配",
        user_id="u_recent_tie",
        settings={"memory": {"retrieval_max_candidates": 5, "context_max_bytes": 4096}},
        limit=2,
    )

    assert [row["memory_id"] for row in ctx.recall_items[:2]] == [
        "same-day-new",
        "same-day-old",
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
