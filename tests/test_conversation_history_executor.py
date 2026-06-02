"""阶段 4：ConversationHistoryExecutor 单元测试。

验证历史查询走专用执行器，基于历史材料输出主题总结。
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


# ── 当前 session 生成摘要 ──

class TestCurrentSessionSummary:
    @pytest.mark.asyncio
    async def test_current_session_prefers_canonical_memory_over_working_memory(self, monkeypatch):
        """当前 session 应优先用统一记忆，保留真实 agent 来源。"""
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="current_session",
            current_session=True,
            requested_format="topic_summary",
        )
        decision = _make_decision(
            semantic_intent=intent,
            context=_make_ctx(
                raw_message="当前session聊过什么",
                semantic_intent=intent,
            ),
        )

        class FakeMemoryService:
            def get_active_conversation_id(self, user_id):
                return "conv-active"

            async def read_conversation_turns(self, **kw):
                assert kw["conversation_id"] == "conv-active"
                return [
                    {
                        "memory_id": "m1",
                        "created_at": "2026-06-02 10:58:08",
                        "conversation_id": "conv-active",
                        "source_agent": "codex",
                        "source_kind": "conversation_turn",
                        "question": "讨论：OPC 适合普通人吗？（第1轮）",
                        "answer": "不太适合普通人，合规和经营压力高。",
                    },
                    {
                        "memory_id": "m2",
                        "created_at": "2026-06-02 10:58:35",
                        "conversation_id": "conv-active",
                        "source_agent": "hermes",
                        "source_kind": "conversation_turn",
                        "question": "讨论：OPC 适合普通人吗？（第2轮）",
                        "answer": "只适合已有技能和稳定业务的人。",
                    },
                ]

            def get_working_memory(self, user_id, limit=10):
                return [
                    {
                        "user": "讨论：OPC 适合普通人吗？（第1轮）",
                        "assistant": "不太适合普通人，合规和经营压力高。",
                        "ts": "2026-06-02 10:58:11",
                    },
                ]

        llm_messages = []

        async def fake_core_llm_chat(messages, temperature=0.3):
            llm_messages.extend(messages)
            return "当前会话主要由 codex 和 hermes 讨论 OPC 是否适合普通人。"

        monkeypatch.setattr(
            "agentmind.memory.service.MemoryService",
            FakeMemoryService,
        )
        monkeypatch.setattr(
            "agentmind.routing.executors.conversation_history.core_llm_chat",
            fake_core_llm_chat,
            raising=False,
        )

        executor = ConversationHistoryExecutor(_mock_registry())
        reply = await executor.build_reply(decision, "u1")

        assert "codex 和 hermes" in reply
        prompt_text = "\n".join(str(m.get("content", "")) for m in llm_messages)
        assert "来源：codex" in prompt_text
        assert "来源：hermes" in prompt_text
        assert "来源：agentmind" not in prompt_text

    @pytest.mark.asyncio
    async def test_current_session_summarizes_from_wm(self, monkeypatch):
        """当前 session 从 Working Memory 生成主题摘要"""
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="current_session",
            current_session=True,
            requested_format="topic_summary",
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

        assert "当前会话的对话记录摘要" in reply
        assert "涉及 Agent：working_memory" in reply
        assert "你会写代码吗？" in reply
        assert "你能查询天气吗？" in reply
        assert "问：" not in reply
        assert "答：" not in reply


# ── 今天生成摘要 ──

class TestTodaySummary:
    @pytest.mark.asyncio
    async def test_today_uses_llm_to_summarize_history_material(self, monkeypatch):
        """今天聊过什么应基于历史材料调用 LLM 总结，而不是机械罗列问答。"""
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="today",
            current_session=False,
            requested_format="topic_summary",
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
                        "created_at": "2026-06-02 01:04:58",
                        "conversation_id": "conv-1",
                        "source_agent": "codex",
                        "source_kind": "discussion_turn",
                        "question": "讨论：幼儿园需要学习ai吗？（第1轮）",
                        "answer": "幼儿园不必系统学习AI，应重视游戏和真实互动。",
                    },
                    {
                        "memory_id": "m2",
                        "created_at": "2026-06-02 03:11:35",
                        "conversation_id": "conv-2",
                        "source_agent": "hermes",
                        "source_kind": "discussion_turn",
                        "question": "讨论：一人公司OPC适合普通人吗？（第1轮）",
                        "answer": "不太适合多数普通人，应先兼职验证收入。",
                    },
                ]

        llm_messages = []

        async def fake_core_llm_chat(messages, temperature=0.3):
            llm_messages.extend(messages)
            return (
                "今天主要聊了两类内容：\n"
                "1. 幼儿园是否需要学习 AI，结论偏向不系统学习。\n"
                "2. 一人公司 OPC 是否适合普通人，结论偏向先兼职验证。"
            )

        monkeypatch.setattr(
            "agentmind.memory.service.MemoryService",
            FakeMemoryService,
        )
        monkeypatch.setattr(
            "agentmind.routing.executors.conversation_history.core_llm_chat",
            fake_core_llm_chat,
            raising=False,
        )

        executor = ConversationHistoryExecutor(_mock_registry())
        reply = await executor.build_reply(decision, "u1")

        assert "今天主要聊了两类内容" in reply
        assert "问：" not in reply
        assert "答：" not in reply
        prompt_text = "\n".join(str(m.get("content", "")) for m in llm_messages)
        assert "幼儿园需要学习ai吗" in prompt_text
        assert "一人公司OPC适合普通人吗" in prompt_text
        assert "codex" in prompt_text
        assert "hermes" in prompt_text

    @pytest.mark.asyncio
    async def test_today_summarizes_from_turns(self, monkeypatch):
        """今天查询使用 read_conversation_turns 并生成摘要"""
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="today",
            current_session=False,
            requested_format="topic_summary",
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

        assert "今天的对话记录摘要" in reply
        assert "涉及 Agent：agentmind, codex" in reply
        assert "你会写代码吗？" in reply
        assert "帮我查今天上海天气" in reply
        assert "问：" not in reply
        assert "答：" not in reply

    @pytest.mark.asyncio
    async def test_today_falls_back_to_memories(self, monkeypatch):
        """MemoryService 失败时回退到 memories"""
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="today",
            current_session=False,
            requested_format="topic_summary",
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

        assert "今天的对话记录摘要" in reply
        assert "你会写代码吗？" in reply
        assert "问：" not in reply
        assert "答：" not in reply


# ── 昨天生成摘要 ──

class TestYesterdaySummary:
    @pytest.mark.asyncio
    async def test_yesterday_summarizes_history(self, monkeypatch):
        """昨天查询使用 read_conversation_turns 并生成摘要"""
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="yesterday",
            current_session=False,
            requested_format="topic_summary",
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

        assert "昨天的对话记录摘要" in reply
        assert "涉及 Agent：codex" in reply
        assert "帮我分析一下销售数据" in reply
        assert "问：" not in reply
        assert "答：" not in reply


# ── 指定日期生成摘要 ──

class TestExplicitDateSummary:
    @pytest.mark.asyncio
    async def test_explicit_date_summarizes_history(self, monkeypatch):
        """指定日期查询使用 read_conversation_turns 并生成摘要"""
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="explicit_date",
            current_session=False,
            explicit_date="2026-05-29",
            requested_format="topic_summary",
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

        assert "2026-05-29 的对话记录摘要" in reply
        assert "涉及 Agent：claude_code" in reply
        assert "写一个排序函数" in reply
        assert "问：" not in reply
        assert "答：" not in reply


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
            requested_format="topic_summary",
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
            requested_format="topic_summary",
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
        assert "主要内容" in reply
        assert "问题0" in reply
        assert "问：" not in reply
        assert "答：" not in reply


# ── 当前 session 无 Working Memory 时回退 ──

class TestCurrentSessionNoWorkingMemory:
    @pytest.mark.asyncio
    async def test_current_session_no_wm_uses_turns(self, monkeypatch):
        """当前 session 无 WM 时用 read_conversation_turns 生成摘要"""
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="current_session",
            current_session=True,
            requested_format="topic_summary",
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

        assert "当前会话的对话记录摘要" in reply
        assert "你好" in reply
        assert "问：" not in reply
        assert "答：" not in reply


# ── run_text / run_json / run_stream 集成 ──

class TestConversationHistoryExecutorRunMethods:
    @pytest.mark.asyncio
    async def test_run_text(self, monkeypatch):
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="today",
            requested_format="topic_summary",
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
        assert "今天的对话记录摘要" in full
        assert "问题1" in full
        assert "问：" not in full
        assert "答：" not in full

    @pytest.mark.asyncio
    async def test_run_json(self, monkeypatch):
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="today",
            requested_format="topic_summary",
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
        assert "今天的对话记录摘要" in data["result"]
        assert "问题1" in data["result"]
        assert "问：" not in data["result"]

    @pytest.mark.asyncio
    async def test_run_stream(self, monkeypatch):
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="today",
            requested_format="topic_summary",
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
        assert "今天的对话记录摘要" in data["content"]
        assert "问题1" in data["content"]
        assert "问：" not in data["content"]


# ── source_kind 标记 ──


class TestConversationHistorySourceKind:
    @pytest.mark.asyncio
    async def test_history_query_writes_unified_conversation_memory(self, monkeypatch):
        """历史查询答案也按统一 conversation_turn 写入记忆。"""
        from agentmind.routing.executors.conversation_history import ConversationHistoryExecutor

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="today",
            requested_format="topic_summary",
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

        assert write_calls == [{
            "source_kind": "conversation_turn",
            "user_message": "今天聊过什么",
        }]

    @pytest.mark.asyncio
    async def test_self_reply_writes_memory_for_agentmind(self, monkeypatch):
        """agentmind 自答也通过 MemoryWriter 写入统一记忆。"""
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

        assert write_calls == [{"source_kind": "conversation_turn"}]


# ── 统一记忆读取测试 ──


class TestHistoryQueryUnifiedMemory:
    @pytest.mark.asyncio
    async def test_history_query_answer_is_read_as_unified_memory(self, monkeypatch):
        """历史查询答案也作为统一记忆读取，交给 LLM 一并总结。"""
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

            turns = await repo.read_conversation_turns(
                user_id="u_pollution",
                time_range_start="2026-05-29 00:00:00",
                time_range_end="2026-05-29 23:59:59",
            )

            ids = [t["memory_id"] for t in turns]
            assert "turn-normal" in ids
            assert "turn-history-answer" in ids
