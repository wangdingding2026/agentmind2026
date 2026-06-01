"""阶段 4：ConversationHistoryExecutor 单元测试。

验证历史查询走专用执行器，输出统一 Q&A 格式。
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentmind.routing.context import RequestIdentity, RoutingContext, RoutingDecision
from agentmind.routing.semantic_intent import SemanticIntent, SemanticIntentType


# ── helpers ──

def _make_ctx(**kw):
    identity = RequestIdentity(
        trace_id=kw.pop("trace_id", "t1"),
        user_id=kw.pop("user_id", "u1"),
    )
    semantic_intent = kw.pop("semantic_intent", None)
    return RoutingContext(
        identity=identity,
        raw_message=kw.pop("raw_message", "今天聊过什么"),
        memories=kw.pop("memories", []),
        candidates=kw.pop("candidates", []),
        semantic_intent=semantic_intent,
        **kw,
    )


def _make_decision(**kw):
    return RoutingDecision(
        agent_id=kw.pop("agent_id", "agentmind"),
        strategy=kw.pop("strategy", "semantic_intent"),
        confidence=kw.pop("confidence", 0.92),
        reply_text=kw.pop("reply_text", ""),
        semantic_intent=kw.pop("semantic_intent", None),
        context=kw.pop("context", None),
    )


def _mock_registry():
    reg = MagicMock()
    reg.get_executor = MagicMock(return_value=None)
    reg.executors = {}
    return reg


def _mock_mem(monkeypatch):
    """统一 mock MemoryService.read_conversation_turns 为空，让测试走 memories 回退路径。"""
    class FakeMemoryService:
        def get_working_memory(self, user_id, limit=10):
            return []

        def get_active_conversation_id(self, user_id):
            return ""

        async def read_conversation_turns(self, **kw):
            return []

    monkeypatch.setattr(
        "agentmind.memory.service.MemoryService",
        FakeMemoryService,
    )


# ── 当前 session 输出 Q&A（Working Memory） ──

class TestCurrentSessionQA:
    @pytest.mark.asyncio
    async def test_current_session_outputs_qa_from_wm(self, monkeypatch):
        """当前 session 从 Working Memory 输出 问：/答： 格式"""
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="current_session",
            current_session=True,
            requested_format="qa_summary",
        )
        decision = _make_decision(
            semantic_intent=intent,
            context=_make_ctx(
                raw_message="当前session我们聊过什么内容",
                semantic_intent=intent,
            ),
        )

        class FakeMemoryService:
            def get_working_memory(self, user_id, limit=10):
                return [
                    {
                        "user": "你会写代码吗？",
                        "assistant": "可以路由给 codex。",
                        "ts": "2026-05-29 19:02:07",
                    },
                    {
                        "user": "你能查询天气吗？",
                        "assistant": "可以路由给搜索 Agent。",
                        "ts": "2026-05-29 19:05:12",
                    },
                ]

        monkeypatch.setattr(
            "agentmind.memory.service.MemoryService",
            FakeMemoryService,
        )
        monkeypatch.setattr(
            "agentmind.routing.executors.base.record_task_end",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "agentmind.routing.executors.base.MemoryWriter.write_task",
            AsyncMock(),
        )

        executor = ConversationHistoryExecutor(_mock_registry())
        reply = await executor.build_reply(decision, "u1")

        assert "问：你会写代码吗？" in reply
        assert "答：可以路由给 codex。" in reply
        assert "问：你能查询天气吗？" in reply
        assert "答：可以路由给搜索 Agent。" in reply


# ── 今天输出 Q&A ──

class TestTodayQA:
    @pytest.mark.asyncio
    async def test_today_outputs_qa_from_turns(self, monkeypatch):
        """今天查询使用 read_conversation_turns"""
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="today",
            current_session=False,
            requested_format="qa_summary",
        )
        decision = _make_decision(
            semantic_intent=intent,
            context=_make_ctx(
                raw_message="今天聊过什么",
                semantic_intent=intent,
            ),
        )

        class FakeMemoryService:
            async def read_conversation_turns(self, **kw):
                return [
                    {
                        "memory_id": "m1",
                        "created_at": "2026-05-29 19:02:07",
                        "conversation_id": "conv-1",
                        "source_agent": "agentmind",
                        "source_kind": "conversation_turn",
                        "question": "你会写代码吗？",
                        "answer": "可以路由给 codex。",
                    },
                    {
                        "memory_id": "m2",
                        "created_at": "2026-05-29 19:10:00",
                        "conversation_id": "conv-1",
                        "source_agent": "codex",
                        "source_kind": "conversation_turn",
                        "question": "帮我查今天上海天气",
                        "answer": "上海今天晴，28°C",
                    },
                ]

        monkeypatch.setattr(
            "agentmind.memory.service.MemoryService",
            FakeMemoryService,
        )
        monkeypatch.setattr(
            "agentmind.routing.executors.base.record_task_end",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "agentmind.routing.executors.base.MemoryWriter.write_task",
            AsyncMock(),
        )

        executor = ConversationHistoryExecutor(_mock_registry())
        reply = await executor.build_reply(decision, "u1")

        assert "问：你会写代码吗？" in reply
        assert "答：可以路由给 codex。" in reply
        assert "问：帮我查今天上海天气" in reply
        assert "答：上海今天晴，28°C" in reply

    @pytest.mark.asyncio
    async def test_today_falls_back_to_memories(self, monkeypatch):
        """MemoryService 失败时回退到 memories"""
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="today",
            current_session=False,
            requested_format="qa_summary",
        )
        decision = _make_decision(
            semantic_intent=intent,
            context=_make_ctx(
                raw_message="今天聊过什么",
                semantic_intent=intent,
                memories=[
                    {
                        "memory_id": "m1",
                        "content": "你会写代码吗？",
                        "summary": "[agentmind] 可以路由给 codex。",
                        "source_agent": "agentmind",
                        "created_at": "2026-05-29 19:02:07",
                    },
                ],
            ),
        )

        _mock_mem(monkeypatch)

        executor = ConversationHistoryExecutor(_mock_registry())
        reply = await executor.build_reply(decision, "u1")

        assert "问：你会写代码吗？" in reply
        assert "答：可以路由给 codex。" in reply


# ── 昨天输出 Q&A ──

class TestYesterdayQA:
    @pytest.mark.asyncio
    async def test_yesterday_outputs_qa(self, monkeypatch):
        """昨天查询使用 read_conversation_turns"""
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="yesterday",
            current_session=False,
            requested_format="qa_summary",
        )
        decision = _make_decision(
            semantic_intent=intent,
            context=_make_ctx(
                raw_message="昨天做过什么",
                semantic_intent=intent,
            ),
        )

        class FakeMemoryService:
            async def read_conversation_turns(self, **kw):
                return [
                    {
                        "memory_id": "m3",
                        "created_at": "2026-05-28 14:00:00",
                        "conversation_id": "conv-2",
                        "source_agent": "codex",
                        "source_kind": "conversation_turn",
                        "question": "帮我分析一下销售数据",
                        "answer": "销售数据已分析",
                    },
                ]

        monkeypatch.setattr(
            "agentmind.memory.service.MemoryService",
            FakeMemoryService,
        )

        executor = ConversationHistoryExecutor(_mock_registry())
        reply = await executor.build_reply(decision, "u1")

        assert "问：帮我分析一下销售数据" in reply
        assert "答：销售数据已分析" in reply


# ── 指定日期输出 Q&A ──

class TestExplicitDateQA:
    @pytest.mark.asyncio
    async def test_explicit_date_outputs_qa(self, monkeypatch):
        """指定日期查询使用 read_conversation_turns"""
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="explicit_date",
            current_session=False,
            explicit_date="2026-05-29",
            requested_format="qa_summary",
        )
        decision = _make_decision(
            semantic_intent=intent,
            context=_make_ctx(
                raw_message="5月29日聊过什么",
                semantic_intent=intent,
            ),
        )

        class FakeMemoryService:
            async def read_conversation_turns(self, **kw):
                return [
                    {
                        "memory_id": "m4",
                        "created_at": "2026-05-29 10:00:00",
                        "conversation_id": "conv-3",
                        "source_agent": "claude_code",
                        "source_kind": "conversation_turn",
                        "question": "写一个排序函数",
                        "answer": "已完成排序函数",
                    },
                ]

        monkeypatch.setattr(
            "agentmind.memory.service.MemoryService",
            FakeMemoryService,
        )

        executor = ConversationHistoryExecutor(_mock_registry())
        reply = await executor.build_reply(decision, "u1")

        assert "问：写一个排序函数" in reply
        assert "答：已完成排序函数" in reply


# ── 无记录时给明确提示 ──

class TestNoRecords:
    @pytest.mark.asyncio
    async def test_no_records_returns_clear_message(self, monkeypatch):
        """无记录时返回明确提示"""
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="today",
            current_session=False,
            requested_format="qa_summary",
        )
        decision = _make_decision(
            semantic_intent=intent,
            context=_make_ctx(
                raw_message="今天聊过什么",
                semantic_intent=intent,
                memories=[],
            ),
        )

        _mock_mem(monkeypatch)

        executor = ConversationHistoryExecutor(_mock_registry())
        reply = await executor.build_reply(decision, "u1")

        assert "没有" in reply
        assert "等" not in reply or "话题" not in reply


# ── 不输出"等 N 个话题"作为主结果 ──

class TestNoTopicSummary:
    @pytest.mark.asyncio
    async def test_no_deng_n_topic_in_main_result(self, monkeypatch):
        """主结果不应包含 等 N 个话题"""
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="today",
            current_session=False,
            requested_format="qa_summary",
        )
        decision = _make_decision(
            semantic_intent=intent,
            context=_make_ctx(
                raw_message="今天聊过什么",
                semantic_intent=intent,
                memories=[],
            ),
        )

        class FakeMemoryService:
            async def read_conversation_turns(self, **kw):
                return [
                    {
                        "memory_id": f"m{i}",
                        "created_at": f"2026-05-29 19:{i:02d}:00",
                        "conversation_id": "conv-x",
                        "source_agent": "agentmind",
                        "source_kind": "conversation_turn",
                        "question": f"问题{i}",
                        "answer": f"回答{i}",
                    }
                    for i in range(6)
                ]

        monkeypatch.setattr(
            "agentmind.memory.service.MemoryService",
            FakeMemoryService,
        )

        executor = ConversationHistoryExecutor(_mock_registry())
        reply = await executor.build_reply(decision, "u1")

        assert "等" not in reply or "话题" not in reply
        assert "问：" in reply
        assert "答：" in reply


# ── 当前 session 无 Working Memory 时回退 ──

class TestCurrentSessionNoWorkingMemory:
    @pytest.mark.asyncio
    async def test_current_session_no_wm_uses_turns(self, monkeypatch):
        """当前 session 无 WM 时用 read_conversation_turns"""
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="current_session",
            current_session=True,
            requested_format="qa_summary",
        )
        decision = _make_decision(
            semantic_intent=intent,
            context=_make_ctx(
                raw_message="当前会话聊过什么",
                semantic_intent=intent,
            ),
        )

        class FakeMemoryService:
            def get_working_memory(self, user_id, limit=10):
                return []

            def get_active_conversation_id(self, user_id):
                return "conv-active"

            async def read_conversation_turns(self, **kw):
                return [
                    {
                        "memory_id": "m1",
                        "created_at": "2026-05-29 10:00:00",
                        "conversation_id": "conv-active",
                        "source_agent": "agentmind",
                        "source_kind": "conversation_turn",
                        "question": "你好",
                        "answer": "你好！",
                    },
                ]

        monkeypatch.setattr(
            "agentmind.memory.service.MemoryService",
            FakeMemoryService,
        )

        executor = ConversationHistoryExecutor(_mock_registry())
        reply = await executor.build_reply(decision, "u1")

        assert "问：你好" in reply
        assert "答：你好！" in reply


# ── run_text / run_json / run_stream 集成 ──

class TestConversationHistoryExecutorRunMethods:
    @pytest.mark.asyncio
    async def test_run_text(self, monkeypatch):
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="today",
            requested_format="qa_summary",
        )
        decision = _make_decision(
            semantic_intent=intent,
            context=_make_ctx(
                raw_message="今天聊过什么",
                semantic_intent=intent,
                memories=[],
            ),
        )

        class FakeMemoryService:
            async def read_conversation_turns(self, **kw):
                return [
                    {
                        "memory_id": "m1",
                        "created_at": "2026-05-29 10:00:00",
                        "conversation_id": "conv-1",
                        "source_agent": "agentmind",
                        "source_kind": "conversation_turn",
                        "question": "问题1",
                        "answer": "回答1",
                    },
                ]

        monkeypatch.setattr(
            "agentmind.memory.service.MemoryService",
            FakeMemoryService,
        )
        monkeypatch.setattr(
            "agentmind.routing.executors.base.record_task_end",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "agentmind.routing.executors.base.MemoryWriter.write_task",
            AsyncMock(),
        )

        executor = ConversationHistoryExecutor(_mock_registry())
        chunks = []
        async for chunk in executor.run_text(decision, "t1", "u1"):
            chunks.append(chunk)

        full = "".join(chunks)
        assert "问：问题1" in full
        assert "答：回答1" in full

    @pytest.mark.asyncio
    async def test_run_json(self, monkeypatch):
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="today",
            requested_format="qa_summary",
        )
        decision = _make_decision(
            semantic_intent=intent,
            context=_make_ctx(
                raw_message="今天聊过什么",
                semantic_intent=intent,
                memories=[],
            ),
        )

        class FakeMemoryService:
            async def read_conversation_turns(self, **kw):
                return [
                    {
                        "memory_id": "m1",
                        "created_at": "2026-05-29 10:00:00",
                        "conversation_id": "conv-1",
                        "source_agent": "agentmind",
                        "source_kind": "conversation_turn",
                        "question": "问题1",
                        "answer": "回答1",
                    },
                ]

        monkeypatch.setattr(
            "agentmind.memory.service.MemoryService",
            FakeMemoryService,
        )
        monkeypatch.setattr(
            "agentmind.routing.executors.base.record_task_end",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "agentmind.routing.executors.base.MemoryWriter.write_task",
            AsyncMock(),
        )

        executor = ConversationHistoryExecutor(_mock_registry())
        resp = await executor.run_json(decision, "t1", "u1")

        data = json.loads(resp.body.decode()) if hasattr(resp, "body") else resp
        assert data["agent_id"] == "agentmind"
        assert "问：问题1" in data["result"]

    @pytest.mark.asyncio
    async def test_run_stream(self, monkeypatch):
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="today",
            requested_format="qa_summary",
        )
        decision = _make_decision(
            semantic_intent=intent,
            context=_make_ctx(
                raw_message="今天聊过什么",
                semantic_intent=intent,
                memories=[],
            ),
        )

        class FakeMemoryService:
            async def read_conversation_turns(self, **kw):
                return [
                    {
                        "memory_id": "m1",
                        "created_at": "2026-05-29 10:00:00",
                        "conversation_id": "conv-1",
                        "source_agent": "agentmind",
                        "source_kind": "conversation_turn",
                        "question": "问题1",
                        "answer": "回答1",
                    },
                ]

        monkeypatch.setattr(
            "agentmind.memory.service.MemoryService",
            FakeMemoryService,
        )
        monkeypatch.setattr(
            "agentmind.routing.executors.base.record_task_end",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "agentmind.routing.executors.base.MemoryWriter.write_task",
            AsyncMock(),
        )

        executor = ConversationHistoryExecutor(_mock_registry())
        chunks = []
        async for chunk in executor.run_stream(decision, "t1", "u1"):
            chunks.append(chunk)

        partials = [c for c in chunks if c.get("event") == "partial"]
        assert len(partials) == 1
        data = json.loads(partials[0]["data"])
        assert "问：问题1" in data["content"]


# ── source_kind 标记 ──


class TestConversationHistorySourceKind:
    @pytest.mark.asyncio
    async def test_history_query_writes_conversation_history_answer(self, monkeypatch):
        """历史查询执行器写入 source_kind=conversation_history_answer"""
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="today",
            requested_format="qa_summary",
        )
        decision = _make_decision(
            semantic_intent=intent,
            context=_make_ctx(
                raw_message="今天聊过什么",
                semantic_intent=intent,
                memories=[],
            ),
        )

        class FakeMemoryService:
            async def read_conversation_turns(self, **kw):
                return [
                    {
                        "memory_id": "m1",
                        "created_at": "2026-05-29 10:00:00",
                        "conversation_id": "conv-1",
                        "source_agent": "agentmind",
                        "source_kind": "conversation_turn",
                        "question": "问题1",
                        "answer": "回答1",
                    },
                ]

        monkeypatch.setattr(
            "agentmind.memory.service.MemoryService",
            FakeMemoryService,
        )

        write_calls = []

        async def fake_write_task(trace_id, agent_id, user_message, result, user_id="", source_kind="conversation_turn"):
            write_calls.append({"source_kind": source_kind, "user_message": user_message})

        monkeypatch.setattr(
            "agentmind.routing.executors.base.record_task_end",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "agentmind.routing.executors.base.MemoryWriter.write_task",
            fake_write_task,
        )

        executor = ConversationHistoryExecutor(_mock_registry())
        async for _ in executor.run_text(decision, "t1", "u1"):
            pass

        # agentmind 自答不写入任务记忆（避免自循环）
        assert len(write_calls) == 0

    @pytest.mark.asyncio
    async def test_self_reply_skips_memory_write_for_agentmind(self, monkeypatch):
        """agentmind 自答不通过 MemoryWriter 写入记忆。"""
        from agentmind.routing.executors.self_reply import SelfReplyExecutor

        decision = _make_decision(
            agent_id="agentmind",
            reply_text="我是 AgentMind",
            context=_make_ctx(raw_message="你好"),
        )

        write_calls = []

        async def fake_write_task(trace_id, agent_id, user_message, result, user_id="", source_kind="conversation_turn"):
            write_calls.append({"source_kind": source_kind})

        monkeypatch.setattr(
            "agentmind.routing.executors.self_reply.record_task_update",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "agentmind.routing.executors.base.record_task_end",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "agentmind.routing.executors.base.MemoryWriter.write_task",
            fake_write_task,
        )

        executor = SelfReplyExecutor(_mock_registry())
        async for _ in executor.run_text(decision, "t1", "u1"):
            pass

        # agentmind 自答不写入任务记忆
        assert len(write_calls) == 0


# ── 自污染测试 ──


class TestHistoryQueryNoPollution:
    @pytest.mark.asyncio
    async def test_history_query_answer_does_not_pollute_next_history_query(self, monkeypatch):
        """连续两次问'今天聊过什么'，第二次不会把第一次历史查询答案当主体内容。

        关键验证：read_conversation_turns 默认排除 source_kind=conversation_history_answer，
        所以即使第一次查询答案已写入，第二次查询时也不会出现在 turns 中。
        """
        from agentmind.memory.dto import MemoryWriteCommand
        from agentmind.memory.repository_sqlite import SqliteMemoryRepository
        import tempfile

        # 用真实 repo 做端到端验证
        with tempfile.TemporaryDirectory() as tmp:
            repo = SqliteMemoryRepository(f"{tmp}/memory.db")

            # 写入一条普通对话 turn
            await repo.write_raw_and_card(MemoryWriteCommand(
                memory_id="turn-normal",
                content="帮我写一个排序函数",
                summary="[claude_code] 已完成排序函数",
                user_id="u_pollution",
                source_agent="claude_code",
                source_kind="conversation_turn",
                created_at="2026-05-29 10:00:00",
            ))

            # 写入一条历史查询自答（模拟第一次"今天聊过什么"的回答）
            await repo.write_raw_and_card(MemoryWriteCommand(
                memory_id="turn-history-answer",
                content="今天聊过什么",
                summary="[agentmind] 今天的对话记录：...",
                user_id="u_pollution",
                source_agent="agentmind",
                source_kind="conversation_history_answer",
                created_at="2026-05-29 10:05:00",
            ))

            # read_conversation_turns 默认应排除 conversation_history_answer
            turns = await repo.read_conversation_turns(
                user_id="u_pollution",
                time_range_start="2026-05-29 00:00:00",
                time_range_end="2026-05-29 23:59:59",
            )

            ids = [t["memory_id"] for t in turns]
            assert "turn-normal" in ids
            assert "turn-history-answer" not in ids

            # 确认 include_history_answers=True 时能查到
            all_turns = await repo.read_conversation_turns(
                user_id="u_pollution",
                time_range_start="2026-05-29 00:00:00",
                time_range_end="2026-05-29 23:59:59",
                include_history_answers=True,
            )
            all_ids = [t["memory_id"] for t in all_turns]
            assert "turn-history-answer" in all_ids

