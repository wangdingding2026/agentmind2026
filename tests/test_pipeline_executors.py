"""Phase 4 收尾：执行器 + 副作用 单元测试"""
import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentmind.agents.base import AgentCapability, StreamEvent, StreamEventType, TaskResult
from agentmind.routing.context import RequestIdentity, RoutingContext, RoutingDecision
from agentmind.routing.envelope import PromptEnvelope
from agentmind.routing.executors.base import ExecutorBase
from agentmind.routing.executors.single_agent import SingleAgentExecutor
from agentmind.routing.executors.self_reply import SelfReplyExecutor
from agentmind.routing.side_effects.memory_writer import MemoryWriter
from agentmind.routing.side_effects.session_registry import SessionRegistry, session_registry
from agentmind.routing.side_effects.trace_recorder import TraceRecorder


# ── helpers ──

def _make_ctx(**kw):
    identity = RequestIdentity(trace_id=kw.pop("trace_id", "t1"), user_id=kw.pop("user_id", "u1"))
    return RoutingContext(
        identity=identity,
        raw_message=kw.pop("raw_message", "hello"),
        memories=kw.pop("memories", []),
        candidates=kw.pop("candidates", ["a1", "a2"]),
        **kw,
    )


def _make_decision(**kw):
    return RoutingDecision(
        agent_id=kw.pop("agent_id", "a1"),
        strategy=kw.pop("strategy", "test"),
        confidence=kw.pop("confidence", 0.9),
        fallback_chain=kw.pop("fallback_chain", ["a2"]),
        reply_text=kw.pop("reply_text", ""),
        context=kw.pop("context", _make_ctx()),
    )


def _mock_executor(healthy=True, succeed=True, output="ok", error="fail"):
    ex = MagicMock()
    ex.is_healthy = healthy
    ex.capability = AgentCapability(
        id="a1", name="Test", type="cli", tags=["test"],
        description="", enabled=True, timeout=5,
    )
    if succeed:
        ex.execute = AsyncMock(return_value=TaskResult(success=True, output=output))
    else:
        ex.execute = AsyncMock(return_value=TaskResult(success=False, output="", error=error))
    return ex


def _mock_registry(executors: dict = None):
    reg = MagicMock()
    reg.get_executor = MagicMock(side_effect=lambda aid: (executors or {}).get(aid))
    reg.executors = executors or {}
    return reg


class _TaskServiceRecorder:
    def __init__(self):
        self.calls = []

    async def record_partial_output(self, trace_id, agent_id=None, content="", chunk_index=0):
        self.calls.append({
            "trace_id": trace_id,
            "agent_id": agent_id,
            "content": content,
            "chunk_index": chunk_index,
        })


# ── PromptEnvelope ──

class TestPromptEnvelope:
    def test_empty_memories_with_list(self):
        """列表输入（兼容旧调用方）返回原始消息。"""
        assert PromptEnvelope.build("hello", []) == "hello"

    def test_none_returns_raw(self):
        assert PromptEnvelope.build("hello", None) == "hello"

    def test_with_assembled_context(self):
        from agentmind.memory.dto import MemoryContext
        mc = MemoryContext(
            assembled_context="[相关记忆]\n[agent] 问：「问题」→ 答案",
            working_memory=[],
            recall_items=[],
        )
        result = PromptEnvelope.build("新问题", mc)
        assert "[相关记忆]" in result
        assert "[agent] 问：「问题」→ 答案" in result
        assert "当前指令：新问题" in result

    def test_list_input_returns_raw(self):
        """列表输入不再做格式化（格式化由 ContextAssembler 统一完成）。"""
        mems = [{"content": "问题", "summary": "答案"}]
        result = PromptEnvelope.build("新问题", mems)
        assert result == "新问题"


# ── ExecutorBase ──

class TestExecutorBase:
    @pytest.mark.asyncio
    async def test_execute_with_fallback_first_succeeds(self):
        ex1 = _mock_executor(succeed=True, output="result1")
        ex2 = _mock_executor(succeed=True, output="result2")
        reg = _mock_registry({"a1": ex1, "a2": ex2})

        base = ExecutorBase.__new__(ExecutorBase)
        base._registry = reg

        aid, result, error = await base._execute_with_fallback(["a1", "a2"], "msg")
        assert aid == "a1"
        assert result.output == "result1"
        assert error is None

    @pytest.mark.asyncio
    async def test_execute_with_fallback_first_fails_second_succeeds(self):
        ex1 = _mock_executor(succeed=False)
        ex2 = _mock_executor(succeed=True, output="result2")
        reg = _mock_registry({"a1": ex1, "a2": ex2})

        base = ExecutorBase.__new__(ExecutorBase)
        base._registry = reg

        aid, result, error = await base._execute_with_fallback(["a1", "a2"], "msg")
        assert aid == "a2"
        assert result.output == "result2"

    @pytest.mark.asyncio
    async def test_execute_with_fallback_all_fail(self):
        ex1 = _mock_executor(succeed=False, error="e1")
        ex2 = _mock_executor(succeed=False, error="e2")
        reg = _mock_registry({"a1": ex1, "a2": ex2})

        base = ExecutorBase.__new__(ExecutorBase)
        base._registry = reg

        aid, result, error = await base._execute_with_fallback(["a1", "a2"], "msg")
        assert aid is None
        assert result is None
        assert error == "e2"

    @pytest.mark.asyncio
    async def test_execute_with_fallback_skips_unhealthy(self):
        ex1 = _mock_executor(healthy=False)
        ex2 = _mock_executor(succeed=True, output="ok")
        reg = _mock_registry({"a1": ex1, "a2": ex2})

        base = ExecutorBase.__new__(ExecutorBase)
        base._registry = reg

        aid, result, _ = await base._execute_with_fallback(["a1", "a2"], "msg")
        assert aid == "a2"

    @pytest.mark.asyncio
    async def test_execute_with_fallback_invokes_protocol_gateway(self, monkeypatch):
        from agentmind.agents.base import TaskResult

        ex1 = _mock_executor(succeed=True, output="direct-result")
        reg = _mock_registry({"a1": ex1})

        calls = []

        class FakeGateway:
            def __init__(self, registry):
                self.registry = registry

            async def invoke(self, agent_id, instruction, context=None):
                calls.append((agent_id, instruction, context))
                return TaskResult(success=True, output="gateway-result")

        monkeypatch.setattr("agentmind.routing.executors.base.ProtocolGateway", FakeGateway)

        base = ExecutorBase.__new__(ExecutorBase)
        base._registry = reg

        aid, result, error = await base._execute_with_fallback(["a1"], "msg")

        assert aid == "a1"
        assert result.output == "gateway-result"
        assert calls == [("a1", "msg", None)]
        assert error is None

    @pytest.mark.asyncio
    async def test_agentmind_self_reply_skips_task_memory_write(self, monkeypatch):
        """agentmind 自答不写入任务记忆（避免自循环）。"""
        calls = []

        async def fake_record_task_end(*args, **kwargs):
            return None

        class FakeMemoryWriter:
            @staticmethod
            async def write_task(trace_id, agent_id, user_message, result, user_id="", source_kind="conversation_turn"):
                calls.append({
                    "trace_id": trace_id,
                    "agent_id": agent_id,
                })

        monkeypatch.setattr("agentmind.routing.executors.base.record_task_end", fake_record_task_end)
        monkeypatch.setattr("agentmind.routing.executors.base.MemoryWriter", FakeMemoryWriter)

        executor = ExecutorBase(_mock_registry({}))
        await executor._record_success(
            "tr-self",
            "agentmind",
            "你是谁",
            "我是 AgentMind",
            "u_self",
        )

        assert calls == []  # agentmind 不写入任务记忆


# ── SelfReplyExecutor ──

class TestSelfReplyExecutor:
    @pytest.mark.asyncio
    async def test_self_reply_uses_reply_text(self):
        """SelfReplyExecutor 对非历史查询直接返回 reply_text"""
        decision = _make_decision(
            agent_id="agentmind",
            reply_text="我是 AgentMind，可以帮你路由任务。",
        )
        reply = await SelfReplyExecutor(_mock_registry({}))._build_reply(decision)
        assert reply == "我是 AgentMind，可以帮你路由任务。"

    @pytest.mark.asyncio
    async def test_self_reply_no_reply_text_returns_fallback(self, monkeypatch):
        """SelfReplyExecutor 无 reply_text 且 LLM 不可用时返回兜底提示"""
        async def _fake_llm_reply(self, decision):
            return None

        monkeypatch.setattr(
            "agentmind.routing.executors.self_reply.SelfReplyExecutor._call_llm_for_reply",
            _fake_llm_reply,
        )

        decision = _make_decision(
            agent_id="agentmind",
            reply_text="",
        )
        reply = await SelfReplyExecutor(_mock_registry({}))._build_reply(decision)
        assert "抱歉" in reply

    @pytest.mark.asyncio
    async def test_self_reply_skips_memory_write_for_agentmind(self, monkeypatch):
        """agentmind 自答不通过 MemoryWriter 写入记忆（避免自循环）。"""
        write_task_called = False

        async def fake_write_task(*args, **kwargs):
            nonlocal write_task_called
            write_task_called = True

        decision = _make_decision(
            agent_id="agentmind",
            reply_text="self reply",
            context=_make_ctx(raw_message="hello"),
        )

        monkeypatch.setattr("agentmind.routing.executors.self_reply.record_task_update", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.base.record_task_end", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.base.MemoryWriter.write_task", fake_write_task)

        executor = SelfReplyExecutor(_mock_registry({}))
        chunks = []
        async for chunk in executor.run_text(decision, "t1", "u1"):
            chunks.append(chunk)

        assert chunks == ["self reply"]
        assert not write_task_called  # agentmind 不写任务记忆

    @pytest.mark.asyncio
    async def test_run_json(self, monkeypatch):
        decision = _make_decision(agent_id="agentmind", reply_text="你好，我是AgentMind")

        monkeypatch.setattr("agentmind.routing.executors.self_reply.record_task_update", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

        reg = _mock_registry({})
        executor = SelfReplyExecutor(reg)
        resp = await executor.run_json(decision, "t1", "u1")

        body = json.loads(resp.body.decode()) if hasattr(resp, "body") else resp
        if hasattr(resp, "body"):
            data = json.loads(resp.body.decode())
            assert data["agent_id"] == "agentmind"
            assert data["result"] == "你好，我是AgentMind"

    @pytest.mark.asyncio
    async def test_run_stream(self, monkeypatch):
        decision = _make_decision(agent_id="agentmind", reply_text="hi")

        monkeypatch.setattr("agentmind.routing.executors.self_reply.record_task_update", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

        reg = _mock_registry({})
        executor = SelfReplyExecutor(reg)
        chunks = []
        async for chunk in executor.run_stream(decision, "t1", "u1"):
            chunks.append(chunk)

        partials = [c for c in chunks if c.get("event") == "partial"]
        assert len(partials) == 1
        data = json.loads(partials[0]["data"])
        assert data["content"] == "hi"

    @pytest.mark.asyncio
    async def test_run_stream_records_partial_output_event(self, monkeypatch):
        recorder = _TaskServiceRecorder()
        decision = _make_decision(agent_id="agentmind", reply_text="self reply")

        monkeypatch.setattr("agentmind.routing.executors.self_reply.record_task_update", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.self_reply.TaskService", lambda: recorder)
        monkeypatch.setattr("agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

        executor = SelfReplyExecutor(_mock_registry({}))
        async for _chunk in executor.run_stream(decision, "t1", "u1"):
            pass

        assert recorder.calls == [
            {"trace_id": "t1", "agent_id": "agentmind", "content": "self reply", "chunk_index": 1}
        ]

    @pytest.mark.asyncio
    async def test_run_text(self, monkeypatch):
        decision = _make_decision(agent_id="agentmind", reply_text="text reply")

        monkeypatch.setattr("agentmind.routing.executors.self_reply.record_task_update", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

        reg = _mock_registry({})
        executor = SelfReplyExecutor(reg)
        chunks = []
        async for chunk in executor.run_text(decision, "t1", "u1"):
            chunks.append(chunk)
        assert chunks == ["text reply"]

    @pytest.mark.asyncio
    async def test_run_text_records_partial_output_event(self, monkeypatch):
        recorder = _TaskServiceRecorder()
        decision = _make_decision(agent_id="agentmind", reply_text="self reply")

        monkeypatch.setattr("agentmind.routing.executors.self_reply.record_task_update", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.self_reply.TaskService", lambda: recorder)
        monkeypatch.setattr("agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

        executor = SelfReplyExecutor(_mock_registry({}))
        chunks = []
        async for chunk in executor.run_text(decision, "t1", "u1"):
            chunks.append(chunk)

        assert chunks == ["self reply"]
        assert recorder.calls == [
            {"trace_id": "t1", "agent_id": "agentmind", "content": "self reply", "chunk_index": 1}
        ]


# ── SingleAgentExecutor run_stream with fallback_chain ──

class TestSingleAgentStreamFallback:
    @pytest.mark.asyncio
    async def test_run_stream_first_succeeds(self, monkeypatch):
        async def _fake_stream(msg):
            yield StreamEvent(StreamEventType.CONTENT, "hello")
            yield StreamEvent(StreamEventType.CONTENT, " world")

        ex = _mock_executor(succeed=True)
        ex.execute_stream = _fake_stream
        reg = _mock_registry({"a1": ex})

        decision = _make_decision(agent_id="a1", fallback_chain=[])
        monkeypatch.setattr("agentmind.routing.executors.single_agent.record_task_end", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.single_agent.record_task_update", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

        executor = SingleAgentExecutor(reg)
        chunks = []
        async for chunk in executor.run_stream(decision, "t1", "u1"):
            chunks.append(chunk)

        partials = [c for c in chunks if c.get("event") == "partial"]
        contents = [json.loads(p["data"])["content"] for p in partials]
        assert "".join(contents) == "hello world"

        completed = [c for c in chunks if json.loads(c.get("data", "{}")).get("status") == "completed"]
        assert len(completed) == 1

    @pytest.mark.asyncio
    async def test_run_stream_records_partial_output_events(self, monkeypatch):
        async def _fake_stream(msg):
            yield StreamEvent(StreamEventType.CONTENT, "hello")
            yield StreamEvent(StreamEventType.CONTENT, " world")

        ex = _mock_executor(succeed=True)
        ex.execute_stream = _fake_stream
        reg = _mock_registry({"a1": ex})
        recorder = _TaskServiceRecorder()

        decision = _make_decision(agent_id="a1", fallback_chain=[])
        monkeypatch.setattr("agentmind.routing.executors.single_agent.record_task_end", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.single_agent.record_task_update", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.single_agent.TaskService", lambda: recorder)
        monkeypatch.setattr("agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

        executor = SingleAgentExecutor(reg)
        async for _chunk in executor.run_stream(decision, "t1", "u1"):
            pass

        assert recorder.calls == [
            {"trace_id": "t1", "agent_id": "a1", "content": "hello", "chunk_index": 1},
            {"trace_id": "t1", "agent_id": "a1", "content": " world", "chunk_index": 2},
        ]

    @pytest.mark.asyncio
    async def test_run_stream_first_fails_no_chunk_tries_next(self, monkeypatch):
        async def _fail_stream(msg):
            yield StreamEvent(StreamEventType.ERROR, "fail")
        async def _ok_stream(msg):
            yield StreamEvent(StreamEventType.CONTENT, "recovered")

        ex1 = _mock_executor(succeed=True)
        ex1.execute_stream = _fail_stream
        ex2 = _mock_executor(succeed=True)
        ex2.execute_stream = _ok_stream
        reg = _mock_registry({"a1": ex1, "a2": ex2})

        decision = _make_decision(agent_id="a1", fallback_chain=["a2"])
        monkeypatch.setattr("agentmind.routing.executors.single_agent.record_task_end", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.single_agent.record_task_update", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

        executor = SingleAgentExecutor(reg)
        chunks = []
        async for chunk in executor.run_stream(decision, "t1", "u1"):
            chunks.append(chunk)

        partials = [c for c in chunks if c.get("event") == "partial"]
        assert len(partials) == 1
        assert json.loads(partials[0]["data"])["content"] == "recovered"

    @pytest.mark.asyncio
    async def test_run_stream_first_fails_after_chunk_stops(self, monkeypatch):
        async def _mixed_stream(msg):
            yield StreamEvent(StreamEventType.CONTENT, "partial ok")
            yield StreamEvent(StreamEventType.ERROR, "then fail")

        ex1 = _mock_executor(succeed=True)
        ex1.execute_stream = _mixed_stream
        ex2 = _mock_executor(succeed=True)
        ex2.execute_stream = lambda msg: (_ for _ in ()).__aiter__()  # won't be called
        reg = _mock_registry({"a1": ex1, "a2": ex2})

        decision = _make_decision(agent_id="a1", fallback_chain=["a2"])
        monkeypatch.setattr("agentmind.routing.executors.single_agent.record_task_end", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.single_agent.record_task_update", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

        executor = SingleAgentExecutor(reg)
        chunks = []
        async for chunk in executor.run_stream(decision, "t1", "u1"):
            chunks.append(chunk)

        partials = [c for c in chunks if c.get("event") == "partial"]
        assert len(partials) == 1  # only from a1, didn't switch
        assert json.loads(partials[0]["data"])["content"] == "partial ok"


class TestSingleAgentRunText:
    @pytest.mark.asyncio
    async def test_run_text_with_response_path(self, monkeypatch):
        """response_path 配置正确时提取 JSON 字段"""
        from agentmind.routing.context import RequestIdentity, RoutingContext

        async def _json_stream(msg):
            yield StreamEvent(StreamEventType.CONTENT, '{"payloads":[{"text":"hello world"}]}')

        cap = AgentCapability(
            id="openclaw", name="OpenClaw", type="cli", tags=["general"],
            description="", enabled=True, timeout=5,
            config={"response_path": "payloads.0.text"},
        )
        from agentmind.agents.cli_executor import CLIExecutor
        ex = CLIExecutor(cap)
        ex.is_healthy = True
        ex.execute_stream = _json_stream

        reg = _mock_registry({"openclaw": ex})
        ctx = RoutingContext(
            identity=RequestIdentity(trace_id="t1", user_id="u1"),
            raw_message="hello", candidates=["openclaw"],
        )
        decision = RoutingDecision(
            agent_id="openclaw", strategy="test", confidence=0.9,
            context=ctx,
        )
        monkeypatch.setattr("agentmind.routing.executors.single_agent.record_task_update", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

        executor = SingleAgentExecutor(reg)
        chunks = []
        async for chunk in executor.run_text(decision, "t1", "u1"):
            chunks.append(chunk)
        assert chunks == ["hello world"]

    @pytest.mark.asyncio
    async def test_run_text_without_response_path_streams(self, monkeypatch):
        """无 response_path 时保持流式输出"""
        from agentmind.routing.context import RequestIdentity, RoutingContext

        async def _stream(msg):
            yield StreamEvent(StreamEventType.CONTENT, "chunk1")
            yield StreamEvent(StreamEventType.CONTENT, "chunk2")

        cap = AgentCapability(
            id="a1", name="Agent", type="cli", tags=["general"],
            description="", enabled=True, timeout=5,
        )
        from agentmind.agents.cli_executor import CLIExecutor
        ex = CLIExecutor(cap)
        ex.is_healthy = True
        ex.execute_stream = _stream

        reg = _mock_registry({"a1": ex})
        ctx = RoutingContext(
            identity=RequestIdentity(trace_id="t1", user_id="u1"),
            raw_message="hello", candidates=["a1"],
        )
        decision = RoutingDecision(
            agent_id="a1", strategy="test", confidence=0.9,
            context=ctx,
        )
        monkeypatch.setattr("agentmind.routing.executors.single_agent.record_task_update", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

        executor = SingleAgentExecutor(reg)
        chunks = []
        async for chunk in executor.run_text(decision, "t1", "u1"):
            chunks.append(chunk)
        assert chunks == ["chunk1", "chunk2"]

    @pytest.mark.asyncio
    async def test_run_text_records_partial_output_events(self, monkeypatch):
        from agentmind.routing.context import RequestIdentity, RoutingContext

        async def _stream(msg):
            yield StreamEvent(StreamEventType.CONTENT, "chunk1")
            yield StreamEvent(StreamEventType.CONTENT, "chunk2")

        cap = AgentCapability(
            id="a1", name="Agent", type="cli", tags=["general"],
            description="", enabled=True, timeout=5,
        )
        from agentmind.agents.cli_executor import CLIExecutor
        ex = CLIExecutor(cap)
        ex.is_healthy = True
        ex.execute_stream = _stream

        reg = _mock_registry({"a1": ex})
        ctx = RoutingContext(
            identity=RequestIdentity(trace_id="t1", user_id="u1"),
            raw_message="hello", candidates=["a1"],
        )
        decision = RoutingDecision(
            agent_id="a1", strategy="test", confidence=0.9,
            context=ctx,
        )
        recorder = _TaskServiceRecorder()
        monkeypatch.setattr("agentmind.routing.executors.single_agent.record_task_update", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.single_agent.TaskService", lambda: recorder)
        monkeypatch.setattr("agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

        executor = SingleAgentExecutor(reg)
        chunks = []
        async for chunk in executor.run_text(decision, "t1", "u1"):
            chunks.append(chunk)

        assert chunks == ["chunk1", "chunk2"]
        assert recorder.calls == [
            {"trace_id": "t1", "agent_id": "a1", "content": "chunk1", "chunk_index": 1},
            {"trace_id": "t1", "agent_id": "a1", "content": "chunk2", "chunk_index": 2},
        ]


# ── SessionRegistry ──

class TestSessionRegistry:
    def test_register_unregister(self):
        sr = SessionRegistry()
        q = sr.register_stream_listener("t1")
        assert isinstance(q, asyncio.Queue)
        assert "t1" in sr._streams

        sr.unregister_stream_listener("t1", q)
        assert "t1" not in sr._streams

    def test_broadcast(self):
        sr = SessionRegistry()
        q = sr.register_stream_listener("t1")
        sr.broadcast_stream_chunk("t1", {"event": "test"})
        # chunk should be in backlog
        assert len(sr._streams["t1"]["backlog"]) == 1

    def test_cleanup_stale(self):
        sr = SessionRegistry()
        q = sr.register_stream_listener("t1")
        sr.unregister_stream_listener("t1", q)
        # unregister 后 listeners 为空，条目被删除，cleanup 无事可做
        removed = sr.cleanup_stale_streams(ttl_seconds=600)
        assert removed == 0

    def test_cleanup_stale_with_listeners(self):
        sr = SessionRegistry()
        sr._streams["t1"] = {"listeners": [], "backlog": [], "created_at": time.time() - 1000}
        removed = sr.cleanup_stale_streams(ttl_seconds=600)
        assert removed == 1
        assert "t1" not in sr._streams

    def test_discussion_lifecycle(self):
        sr = SessionRegistry()
        sr.start_discussion("u1")
        assert sr.is_discussion_active("u1")

        sr.stop_discussion("u1")
        assert not sr.is_discussion_active("u1")

        sr.end_discussion("u1")
        assert "u1" not in sr._discussions


# ── TraceRecorder ──

class TestTraceRecorder:
    @pytest.mark.asyncio
    async def test_record_and_get(self, monkeypatch):
        decision = _make_decision(
            agent_id="a1", strategy="explicit",
            fallback_chain=["a2"], reply_text="",
        )
        decision.context.candidates = ["a1", "a2"]

        class FakeTraceService:
            async def record_decision(self, trace_id, recorded_decision, user_id=""):
                assert trace_id == "t1"
                assert recorded_decision is decision
                assert user_id == "u1"

            async def get_trace(self, trace_id):
                assert trace_id == "t1"
                return {"trace_id": trace_id, "summary": "[explicit] -> a1 (conf=0.85)"}

        monkeypatch.setattr(
            "agentmind.routing.side_effects.trace_recorder.TraceService",
            FakeTraceService,
        )

        await TraceRecorder.record_decision("t1", decision, "u1")
        trace = await TraceRecorder.get_trace("t1")

        assert trace is not None
        assert "[explicit] -> a1" in trace["summary"]


# ── SensitiveScanner ──

class TestSensitiveScanner:
    def test_no_sensitive_content(self):
        from agentmind.routing.middleware.sensitive_scanner import SensitiveScanner
        r = SensitiveScanner().scan("普通消息")
        assert not r.flagged

    def test_empty_message(self):
        from agentmind.routing.middleware.sensitive_scanner import SensitiveScanner
        r = SensitiveScanner().scan("")
        assert not r.flagged

    def test_api_key_detected(self):
        from agentmind.routing.middleware.sensitive_scanner import SensitiveScanner
        r = SensitiveScanner().scan("sk-abcdefghijklmnopqrstuvwxyz123456")
        assert r.flagged

    def test_password_detected(self):
        from agentmind.routing.middleware.sensitive_scanner import SensitiveScanner
        r = SensitiveScanner().scan('password = "mysecret"')
        assert r.flagged


# ── CandidatePool ──

class TestCandidatePool:
    def test_filters_unhealthy(self):
        from agentmind.routing.middleware.candidate_pool import CandidatePool
        from agentmind.routing.middleware.sensitive_scanner import ScanResult
        reg = _mock_registry({
            "a1": _mock_executor(healthy=True),
            "a2": _mock_executor(healthy=False),
        })
        candidates = CandidatePool(reg).filter(ScanResult(flagged=False))
        assert candidates == ["a1"]

    def test_blocks_cloud_on_sensitive(self):
        from agentmind.routing.middleware.candidate_pool import CandidatePool
        from agentmind.routing.middleware.sensitive_scanner import ScanResult
        from agentmind.agents.base import AgentCapability
        ex1 = _mock_executor(healthy=True)
        ex1.capability.security_level = "cloud"
        ex2 = _mock_executor(healthy=True)
        ex2.capability.security_level = "local"
        reg = _mock_registry({"a1": ex1, "a2": ex2})
        candidates = CandidatePool(reg).filter(ScanResult(flagged=True))
        assert candidates == ["a2"]

    def test_all_unhealthy_returns_empty(self):
        from agentmind.routing.middleware.candidate_pool import CandidatePool
        from agentmind.routing.middleware.sensitive_scanner import ScanResult
        reg = _mock_registry({
            "a1": _mock_executor(healthy=False),
        })
        candidates = CandidatePool(reg).filter(ScanResult(flagged=False))
        assert candidates == []


# ── ExplicitDirective ──

class TestExplicitDirective:
    @pytest.mark.asyncio
    async def test_no_mention_returns_none(self):
        from agentmind.routing.strategies.explicit_directive import ExplicitDirective
        ctx = _make_ctx(raw_message="普通消息")
        result = await ExplicitDirective(_mock_registry({})).evaluate(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_at_mention_resolves(self):
        from agentmind.routing.strategies.explicit_directive import ExplicitDirective
        ex = _mock_executor(healthy=True)
        reg = _mock_registry({"claude_code": ex})
        ctx = _make_ctx(raw_message="@claude_code 帮我写代码", candidates=["claude_code"])
        result = await ExplicitDirective(reg).evaluate(ctx)
        assert result is not None
        assert result.agent_id == "claude_code"
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_at_mention_not_in_candidates(self):
        from agentmind.routing.strategies.explicit_directive import ExplicitDirective
        ex = _mock_executor(healthy=True)
        reg = _mock_registry({"claude_code": ex})
        # agent exists but not in candidates (e.g., unhealthy)
        ctx = _make_ctx(raw_message="@claude_code hi", candidates=["other"])
        result = await ExplicitDirective(reg).evaluate(ctx)
        assert result is None


# ── RuleEngineStrategy ──

class TestRuleEngineStrategy:
    @pytest.mark.asyncio
    async def test_match_returns_result(self):
        from agentmind.routing.strategies.rule_engine import RuleEngineStrategy
        from agentmind.core.rule_engine import RuleEngine
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("rules: []")
            f.flush()
            from pathlib import Path
            engine = RuleEngine(Path(f.name))
            engine.rules = []  # no rules, falls through
            ctx = _make_ctx(candidates=["a1"])
            result = await RuleEngineStrategy(engine).evaluate(ctx)
            assert result is None  # no matching rules

    @pytest.mark.asyncio
    async def test_empty_candidates_returns_none(self):
        from agentmind.routing.strategies.rule_engine import RuleEngineStrategy
        from unittest.mock import AsyncMock
        engine = AsyncMock()
        engine.match = AsyncMock(return_value=None)
        ctx = _make_ctx(candidates=[])
        result = await RuleEngineStrategy(engine).evaluate(ctx)
        assert result is None


# ── RoutingPipeline integration ──

class TestRoutingPipeline:
    @pytest.mark.asyncio
    async def test_run_returns_decision(self):
        from agentmind.routing.pipeline import RoutingPipeline
        from agentmind.routing.context import RequestIdentity
        ex1 = _mock_executor(healthy=True)
        ex2 = _mock_executor(healthy=True)
        reg = _mock_registry({"a1": ex1, "a2": ex2})
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("rules: []")
            f.flush()
            from agentmind.core.rule_engine import RuleEngine
            from pathlib import Path as _Path
            engine = RuleEngine(_Path(f.name))
            engine.rules = []
            pipeline = RoutingPipeline(reg, engine)
            identity = RequestIdentity(trace_id="t1", user_id="u1")
            decision = await pipeline.run("hello", identity, {})
            assert decision.agent_id in ("a1", "a2")
            assert decision.context is not None

    @pytest.mark.asyncio
    async def test_pipeline_uses_strategy_manager_for_enabled_strategies(self):
        from agentmind.routing.pipeline import RoutingPipeline
        from agentmind.routing.context import RequestIdentity
        from agentmind.services.strategy_manager import StrategyManager

        ex1 = _mock_executor(healthy=True)
        reg = _mock_registry({"a1": ex1})

        class _NoRuleEngine:
            async def match(self, message):
                return None

        manager = StrategyManager(reg, _NoRuleEngine())
        manager.set_enabled("semantic_intent", False)
        pipeline = RoutingPipeline(reg, _NoRuleEngine(), strategy_manager=manager)

        decision = await pipeline.run("hello", RequestIdentity(trace_id="t1", user_id="u1"), {})

        assert decision.agent_id == "a1"
        assert "semantic_intent" not in [s.name for s in manager.get_enabled_strategies({})]

    @pytest.mark.asyncio
    async def test_pipeline_propagates_semantic_intent_from_strategy_result(self):
        from agentmind.routing.pipeline import RoutingPipeline
        from agentmind.routing.context import RequestIdentity
        from agentmind.routing.semantic_intent import SemanticIntent, SemanticIntentType
        from agentmind.routing.strategies.base import RoutingStrategy, StrategyResult

        intent = SemanticIntent(
            intent=SemanticIntentType.CONVERSATION_HISTORY,
            confidence=0.92,
            time_scope="today",
            requested_format="qa_summary",
        )

        class _SemanticStrategy(RoutingStrategy):
            def __init__(self):
                super().__init__(name="semantic_intent", priority=20)

            async def evaluate(self, ctx):
                return StrategyResult(
                    agent_id="agentmind",
                    confidence=0.92,
                    reason="语义意图: conversation_history",
                    semantic_intent=intent,
                )

        class _Manager:
            def get_enabled_strategies(self, settings):
                return [_SemanticStrategy()]

        class _NoRuleEngine:
            async def match(self, message):
                return None

        reg = _mock_registry({})
        pipeline = RoutingPipeline(reg, _NoRuleEngine(), strategy_manager=_Manager())

        decision = await pipeline.run(
            "今天聊过什么",
            RequestIdentity(trace_id="t1", user_id="u1"),
            {},
        )

        assert decision.agent_id == "agentmind"
        assert decision.semantic_intent is intent
        assert decision.context.semantic_intent is intent
