"""飞书通道集成测试：实际覆盖 route_stream、讨论、解析等 Feishu 真实调用路径"""
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentmind.agents.base import AgentCapability, StreamEvent, StreamEventType, TaskResult


class FakeDiscussionMemoryService:
    async def write_memory(self, entry, generate_embedding=True, user_id=""):
        return 1


# ═══════════════════════════════════════
# 1. _parse_discussion 讨论消息解析
# ═══════════════════════════════════════

class TestParseDiscussion:
    def test_two_agents_with_topic(self):
        """@agent1 @agent2 讨论：主题 → 正确解析"""
        from agentmind.services.routing_service import _parse_discussion

        ex1 = _make_healthy_executor("claude_code", "Claude Code")
        ex2 = _make_healthy_executor("hermes", "Hermes")
        reg = _fake_registry({"claude_code": ex1, "hermes": ex2})

        result = _parse_discussion("@claude_code @hermes 讨论：AI的未来", reg)
        assert result is not None
        mentions, topic = result
        assert set(mentions) == {"claude_code", "hermes"}
        assert "AI的未来" in topic

    def test_two_agents_trigger_聊聊(self):
        """@a1 @a2 聊聊 → 触发讨论"""
        from agentmind.services.routing_service import _parse_discussion

        ex1 = _make_healthy_executor("a1", "A1")
        ex2 = _make_healthy_executor("a2", "A2")
        reg = _fake_registry({"a1": ex1, "a2": ex2})

        result = _parse_discussion("@a1 @a2 聊聊今天的事", reg)
        assert result is not None

    def test_single_agent_no_discussion(self):
        """单个 @mention 不触发讨论"""
        from agentmind.services.routing_service import _parse_discussion

        ex = _make_healthy_executor("a1", "A1")
        reg = _fake_registry({"a1": ex})
        result = _parse_discussion("@a1 帮我写代码", reg)
        assert result is None

    def test_no_discussion_keyword(self):
        """有 @mention 但无讨论关键词 → 不触发"""
        from agentmind.services.routing_service import _parse_discussion

        ex1 = _make_healthy_executor("a1", "A1")
        ex2 = _make_healthy_executor("a2", "A2")
        reg = _fake_registry({"a1": ex1, "a2": ex2})
        result = _parse_discussion("@a1 @a2 帮我写代码", reg)
        assert result is None

    def test_fuzzy_name_resolution(self):
        """@Claude 模糊匹配到 claude_code"""
        from agentmind.services.routing_service import _resolve_agent_mention

        ex = _make_healthy_executor("claude_code", "Claude Code")
        reg = _fake_registry({"claude_code": ex})
        aid = _resolve_agent_mention("Claude", reg)
        assert aid == "claude_code"

    def test_topic_preserves_constraints(self):
        """用户附加要求保留在 topic 中"""
        from agentmind.services.routing_service import _parse_discussion

        ex1 = _make_healthy_executor("a", "A")
        ex2 = _make_healthy_executor("b", "B")
        reg = _fake_registry({"a": ex1, "b": ex2})

        result = _parse_discussion(
            "@a @b 讨论：微服务架构，必须从成本和稳定性两个维度分析，每人限100字", reg)
        assert result is not None
        _, topic = result
        assert "成本" in topic
        assert "稳定性" in topic
        assert "限100字" in topic

    def test_topic_without_constraints(self):
        """无附加要求的讨论"""
        from agentmind.services.routing_service import _parse_discussion

        ex1 = _make_healthy_executor("a", "A")
        ex2 = _make_healthy_executor("b", "B")
        reg = _fake_registry({"a": ex1, "b": ex2})

        result = _parse_discussion("@a @b 讨论：AI监管", reg)
        assert result is not None
        _, topic = result
        assert topic == "AI监管"


# ═══════════════════════════════════════
# 2. route_stream 飞书消息路由
# ═══════════════════════════════════════

class TestRouteStream:
    @pytest.mark.asyncio
    async def test_normal_message_routes_to_agent(self, monkeypatch):
        """普通消息 → route_stream 走新管道 → 路由到 Agent → yield 文本"""
        from agentmind.api.router import route_stream

        ex = _make_healthy_executor("echo_agent", "Echo", tags=["general"])

        async def _fake_stream(msg):
            yield StreamEvent(StreamEventType.CONTENT, "回复内容")

        ex.execute_stream = _fake_stream
        reg = _fake_registry({"echo_agent": ex})
        engine = _fake_rule_engine()
        settings = {"routing": {"use_new_pipeline": True}}

        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_start", AsyncMock())
        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_end", AsyncMock())
        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_update", AsyncMock())
        monkeypatch.setattr(
            "agentmind.routing.side_effects.trace_recorder.TraceRecorder.record_decision", AsyncMock())
        monkeypatch.setattr(
            "agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

        chunks = []
        async for chunk in route_stream("你好", "u1", reg, engine, settings):
            chunks.append(chunk)

        # 应该有 agent 标签 + 回复内容
        assert len(chunks) >= 1
        assert any("回复内容" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_self_reply_yields_text(self, monkeypatch):
        """LLM 决定自答时 route_stream yield 回复文本"""
        from agentmind.api.router import route_stream
        from agentmind.routing.context import RoutingContext, RoutingDecision, RequestIdentity

        ex = _make_healthy_executor("a1", "Agent", tags=["general"])
        reg = _fake_registry({"a1": ex})
        engine = _fake_rule_engine()
        settings = {"routing": {"use_new_pipeline": True}}

        # Mock pipeline 返回自答决策
        decision = RoutingDecision(
            agent_id="agentmind", strategy="LLM 自答", confidence=0.9,
            reply_text="你好，我是 AgentMind",
            context=RoutingContext(
                identity=RequestIdentity(trace_id="t1", user_id="u1"),
                raw_message="你好", candidates=["a1"],
            ),
        )
        async def _fake_run(self, msg, identity, settings, is_retry=False):
            return decision

        monkeypatch.setattr(
            "agentmind.routing.pipeline.RoutingPipeline.run", _fake_run)
        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_start", AsyncMock())
        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_end", AsyncMock())
        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_update", AsyncMock())
        monkeypatch.setattr(
            "agentmind.routing.side_effects.trace_recorder.TraceRecorder.record_decision", AsyncMock())
        monkeypatch.setattr(
            "agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

        chunks = []
        async for chunk in route_stream("你好", "u1", reg, engine, settings):
            chunks.append(chunk)

        assert any("AgentMind" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_no_agent_returns_error(self, monkeypatch):
        """无可用 Agent → route_stream yield 错误提示"""
        from agentmind.api.router import route_stream
        from agentmind.routing.context import RoutingContext, RoutingDecision, RequestIdentity

        ex = _make_healthy_executor("a1", "Agent", tags=["general"])
        ex.is_healthy = False
        reg = _fake_registry({"a1": ex})
        engine = _fake_rule_engine()
        settings = {"routing": {"use_new_pipeline": True}}

        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_start", AsyncMock())
        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_update", AsyncMock())

        chunks = []
        async for chunk in route_stream("hello", "u1", reg, engine, settings):
            chunks.append(chunk)

        assert any("没有可用" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_response_path_json_extraction(self, monkeypatch):
        """response_path 配置时 route_stream 正确提取 JSON 字段"""
        from agentmind.api.router import route_stream

        cap = AgentCapability(
            id="openclaw", name="OpenClaw", type="cli",
            tags=["general"], description="", enabled=True, timeout=5,
            config={"response_path": "payloads.0.text"},
        )
        from agentmind.agents.cli_executor import CLIExecutor
        ex = CLIExecutor(cap)
        ex.is_healthy = True

        async def _json_stream(msg):
            yield StreamEvent(StreamEventType.CONTENT,
                              '{"payloads":[{"text":"实际回复"}]}')

        ex.execute_stream = _json_stream
        reg = _fake_registry({"openclaw": ex})
        engine = _fake_rule_engine()
        settings = {"routing": {"use_new_pipeline": True}}

        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_start", AsyncMock())
        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_end", AsyncMock())
        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_update", AsyncMock())
        monkeypatch.setattr(
            "agentmind.routing.side_effects.trace_recorder.TraceRecorder.record_decision", AsyncMock())
        monkeypatch.setattr(
            "agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

        chunks = []
        async for chunk in route_stream("@openclaw hi", "u1", reg, engine, settings):
            chunks.append(chunk)

        # 不应该包含原始 JSON
        full_text = "".join(chunks)
        assert "payloads" not in full_text
        assert "实际回复" in full_text

    @pytest.mark.asyncio
    async def test_history_query_is_not_handled_by_protocol_router(self, monkeypatch):
        """历史查询不是协议命令，必须继续进入语义路由 pipeline。"""
        from agentmind.api.router import route_stream
        from agentmind.routing.context import RequestIdentity, RoutingContext, RoutingDecision

        ex = _make_healthy_executor("echo_agent", "Echo", tags=["general"])
        reg = _fake_registry({"echo_agent": ex})
        engine = _fake_rule_engine()
        settings = {"routing": {"use_new_pipeline": True}}
        calls = []

        async def _fake_run(self, msg, identity, settings, is_retry=False):
            calls.append((msg, identity.user_id))
            return RoutingDecision(
                agent_id="agentmind",
                strategy="semantic_intent",
                confidence=0.9,
                reply_text="今天的对话记录",
                context=RoutingContext(
                    identity=RequestIdentity(trace_id=identity.trace_id, user_id=identity.user_id),
                    raw_message=msg,
                    candidates=["echo_agent"],
                ),
            )

        monkeypatch.setattr("agentmind.routing.pipeline.RoutingPipeline.run", _fake_run)
        monkeypatch.setattr("agentmind.services.routing_service.record_task_start", AsyncMock())
        monkeypatch.setattr("agentmind.services.routing_service.record_task_end", AsyncMock())
        monkeypatch.setattr("agentmind.services.routing_service.record_task_update", AsyncMock())
        monkeypatch.setattr(
            "agentmind.routing.side_effects.trace_recorder.TraceRecorder.record_decision",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "agentmind.routing.executors.base.MemoryWriter.write_task",
            AsyncMock(),
        )

        chunks = []
        async for chunk in route_stream("今天都聊过什么内容，帮我总结一下", "u1", reg, engine, settings):
            chunks.append(chunk)

        assert calls == [("今天都聊过什么内容，帮我总结一下", "u1")]
        assert any("今天的对话记录" in chunk for chunk in chunks)


# ═══════════════════════════════════════
# 3. _run_discussion 讨论循环
# ═══════════════════════════════════════

class TestRunDiscussion:
    @pytest.mark.asyncio
    async def test_single_turn_discussion(self, monkeypatch):
        """讨论循环：Agent 轮流发言一轮后停止"""
        from agentmind.services.routing_service import _run_discussion
        from agentmind.routing.side_effects.session_registry import session_registry as _session

        sent_messages = []

        async def _fake_send(text):
            sent_messages.append(text)

        async def _fake_stream_a(msg):
            _session.stop_discussion("u1")  # 第一轮后停
            yield StreamEvent(StreamEventType.CONTENT, "A的观点")
        async def _fake_stream_b(msg):
            yield StreamEvent(StreamEventType.CONTENT, "B的观点")

        ex_a = _make_healthy_executor("a", "AgentA")
        ex_a.execute_stream = _fake_stream_a
        ex_b = _make_healthy_executor("b", "AgentB")
        ex_b.execute_stream = _fake_stream_b
        reg = _fake_registry({"a": ex_a, "b": ex_b})

        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_start", AsyncMock())
        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_end", AsyncMock())
        monkeypatch.setattr(
            "agentmind.api.router.MemoryService", FakeDiscussionMemoryService)

        _session.start_discussion("u1")
        await _run_discussion("测试话题", ["a", "b"], "u1", reg, _fake_send)

        # 应该只有第一轮发言（因为 stream 里喊停了）
        a_messages = [m for m in sent_messages if "AgentA" in m]
        assert len(a_messages) >= 1

    @pytest.mark.asyncio
    async def test_response_path_in_discussion(self, monkeypatch):
        """讨论中 OpenClaw 返回 JSON → 正确提取文本"""
        from agentmind.services.routing_service import _run_discussion
        from agentmind.routing.side_effects.session_registry import session_registry as _session

        sent_messages = []

        async def _fake_send(text):
            sent_messages.append(text)

        async def _json_stream(msg):
            _session.stop_discussion("u1")
            yield StreamEvent(StreamEventType.CONTENT,
                              '{"payloads":[{"text":"JSON内的观点"}]}')

        cap = AgentCapability(
            id="openclaw", name="OpenClaw", type="cli",
            tags=["general"], description="", enabled=True, timeout=5,
            config={"response_path": "payloads.0.text"},
        )
        from agentmind.agents.cli_executor import CLIExecutor
        ex_a = CLIExecutor(cap)
        ex_a.is_healthy = True
        ex_a.execute_stream = _json_stream

        async def _normal_stream(msg):
            yield StreamEvent(StreamEventType.CONTENT, "普通文本观点")

        ex_b = _make_healthy_executor("hermes", "Hermes")
        ex_b.execute_stream = _normal_stream
        reg = _fake_registry({"openclaw": ex_a, "hermes": ex_b})

        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_start", AsyncMock())
        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_end", AsyncMock())
        monkeypatch.setattr(
            "agentmind.api.router.MemoryService", FakeDiscussionMemoryService)

        _session.start_discussion("u1")
        await _run_discussion("测试", ["openclaw", "hermes"], "u1", reg, _fake_send)

        # 不应出现原始 JSON 中的 payloads
        for msg in sent_messages:
            assert "payloads" not in msg, f"消息包含原始 JSON: {msg[:100]}"

    @pytest.mark.asyncio
    async def test_topic_with_constraints_in_prompt(self, monkeypatch):
        """用户附带约束（限字/维度）→ 首轮 prompt 包含约束"""
        from agentmind.services.routing_service import _run_discussion
        from agentmind.routing.side_effects.session_registry import session_registry as _session

        sent_messages = []
        agent_prompts = []

        async def _fake_send(text):
            sent_messages.append(text)

        async def _fake_stream(msg):
            agent_prompts.append(msg)
            _session.stop_discussion("u1")
            yield StreamEvent(StreamEventType.CONTENT, "观点")

        ex_a = _make_healthy_executor("a", "AgentA")
        ex_a.execute_stream = _fake_stream
        ex_b = _make_healthy_executor("b", "AgentB")
        ex_b.execute_stream = _fake_stream
        reg = _fake_registry({"a": ex_a, "b": ex_b})

        monkeypatch.setattr("agentmind.services.routing_service.record_task_start", AsyncMock())
        monkeypatch.setattr("agentmind.services.routing_service.record_task_end", AsyncMock())
        monkeypatch.setattr("agentmind.api.router.MemoryService", FakeDiscussionMemoryService)

        _session.start_discussion("u1")
        topic = "AI监管，必须从法律和技术两个角度分析"
        await _run_discussion(topic, ["a", "b"], "u1", reg, _fake_send)

        # 首轮 prompt 应该包含用户的完整要求
        assert len(agent_prompts) >= 1
        first_prompt = agent_prompts[0]
        assert "法律" in first_prompt
        assert "技术" in first_prompt
        # 用户自己没说限字 → 系统补充默认限字
        assert "300" in first_prompt

    @pytest.mark.asyncio
    async def test_topic_with_word_limit_no_default(self, monkeypatch):
        """用户已指定限字 → 不追加系统默认限字"""
        from agentmind.services.routing_service import _run_discussion
        from agentmind.routing.side_effects.session_registry import session_registry as _session

        agent_prompts = []

        async def _fake_send(text):
            pass

        async def _fake_stream(msg):
            agent_prompts.append(msg)
            _session.stop_discussion("u1")
            yield StreamEvent(StreamEventType.CONTENT, "观点")

        ex_a = _make_healthy_executor("a", "AgentA")
        ex_a.execute_stream = _fake_stream
        ex_b = _make_healthy_executor("b", "AgentB")
        ex_b.execute_stream = _fake_stream
        reg = _fake_registry({"a": ex_a, "b": ex_b})

        monkeypatch.setattr("agentmind.services.routing_service.record_task_start", AsyncMock())
        monkeypatch.setattr("agentmind.services.routing_service.record_task_end", AsyncMock())
        monkeypatch.setattr("agentmind.api.router.MemoryService", FakeDiscussionMemoryService)

        _session.start_discussion("u1")
        await _run_discussion("AI监管，每人限100字", ["a", "b"], "u1", reg, _fake_send)

        first_prompt = agent_prompts[0]
        assert "限100字" in first_prompt
        assert "300" not in first_prompt

    @pytest.mark.asyncio
    async def test_word_limit_applies_to_all_turns(self, monkeypatch):
        """用户指定限50字 → 所有轮次都限50字，不是只首轮"""
        from agentmind.services.routing_service import _run_discussion
        from agentmind.routing.side_effects.session_registry import session_registry as _session

        agent_prompts = []

        async def _fake_send(text):
            pass

        call_count = [0]
        async def _fake_stream(msg):
            agent_prompts.append(msg)
            call_count[0] += 1
            if call_count[0] >= 3:  # 3轮后停
                _session.stop_discussion("u1")
            yield StreamEvent(StreamEventType.CONTENT, "观点")

        ex_a = _make_healthy_executor("a", "AgentA")
        ex_a.execute_stream = _fake_stream
        ex_b = _make_healthy_executor("b", "AgentB")
        ex_b.execute_stream = _fake_stream
        reg = _fake_registry({"a": ex_a, "b": ex_b})

        monkeypatch.setattr("agentmind.services.routing_service.record_task_start", AsyncMock())
        monkeypatch.setattr("agentmind.services.routing_service.record_task_end", AsyncMock())
        monkeypatch.setattr("agentmind.api.router.MemoryService", FakeDiscussionMemoryService)

        _session.start_discussion("u1")
        # 模拟用户实际说法："每次回复限制50字"
        await _run_discussion(
            "现在小学生需要学习ai吗。每次回复限制50字", ["a", "b"], "u1", reg, _fake_send)

        # 前 3 个是讨论轮次，最后一个是总结
        discussion_prompts = agent_prompts[:-1]
        summary_prompt = agent_prompts[-1] if len(agent_prompts) > 3 else ""

        assert len(discussion_prompts) >= 2
        for i, prompt in enumerate(discussion_prompts):
            assert "限50字" in prompt, f"讨论第{i+1}轮缺少限50字: {prompt[:80]}"
            assert "300" not in prompt, f"讨论第{i+1}轮出现了300字: {prompt[:80]}"

        # 总结也应有限制
        if summary_prompt:
            assert "限50字" in summary_prompt, f"总结缺少限50字: {summary_prompt[:80]}"

    @pytest.mark.asyncio
    async def test_word_limit_accepts_ge_zi_expression(self, monkeypatch):
        """用户说“20个字”时应识别为限20字，而不是回退到默认300字"""
        from agentmind.services.routing_service import _run_discussion
        from agentmind.routing.side_effects.session_registry import session_registry as _session

        agent_prompts = []

        async def _fake_send(text):
            pass

        call_count = [0]

        async def _fake_stream(msg):
            agent_prompts.append(msg)
            call_count[0] += 1
            if call_count[0] >= 3:
                _session.stop_discussion("u1")
            yield StreamEvent(StreamEventType.CONTENT, "观点")

        ex_a = _make_healthy_executor("a", "AgentA")
        ex_a.execute_stream = _fake_stream
        ex_b = _make_healthy_executor("b", "AgentB")
        ex_b.execute_stream = _fake_stream
        reg = _fake_registry({"a": ex_a, "b": ex_b})

        monkeypatch.setattr("agentmind.services.routing_service.record_task_start", AsyncMock())
        monkeypatch.setattr("agentmind.services.routing_service.record_task_end", AsyncMock())
        monkeypatch.setattr("agentmind.api.router.MemoryService", FakeDiscussionMemoryService)

        _session.start_discussion("u1")
        await _run_discussion(
            "幼儿园需要学习ai吗？回复限制20个字",
            ["a", "b"],
            "u1",
            reg,
            _fake_send,
        )

        assert len(agent_prompts) >= 3
        for prompt in agent_prompts:
            assert "限20字" in prompt, f"prompt 缺少限20字: {prompt[:80]}"
            assert "300" not in prompt, f"prompt 错误回退到默认300字: {prompt[:80]}"

    @pytest.mark.asyncio
    async def test_followup_prompt_keeps_original_topic_anchor(self, monkeypatch):
        """上一轮偏题时，下一轮和总结仍应锚定原始议题"""
        from agentmind.services.routing_service import _run_discussion
        from agentmind.routing.side_effects.session_registry import session_registry as _session

        agent_prompts = []

        async def _fake_send(text):
            pass

        async def _fake_stream(msg):
            agent_prompts.append(msg)
            if len(agent_prompts) == 2:
                _session.stop_discussion("u1")
            yield StreamEvent(
                StreamEventType.CONTENT,
                "扩散模型、世界模型与反馈延迟会造成控制系统振荡。",
            )

        ex_a = _make_healthy_executor("a", "AgentA")
        ex_a.execute_stream = _fake_stream
        ex_b = _make_healthy_executor("b", "AgentB")
        ex_b.execute_stream = _fake_stream
        reg = _fake_registry({"a": ex_a, "b": ex_b})

        monkeypatch.setattr("agentmind.services.routing_service.record_task_start", AsyncMock())
        monkeypatch.setattr("agentmind.services.routing_service.record_task_end", AsyncMock())
        monkeypatch.setattr("agentmind.api.router.MemoryService", FakeDiscussionMemoryService)

        topic = "幼儿园需要学习ai吗？不要偏离核心主题"
        _session.start_discussion("u1")
        await _run_discussion(topic, ["a", "b"], "u1", reg, _fake_send)

        followup_prompt = agent_prompts[1]
        summary_prompt = agent_prompts[-1]
        assert f'原始议题："{topic}"' in followup_prompt
        assert "若上一轮偏离原始议题" in followup_prompt
        assert f'原始议题："{topic}"' in summary_prompt
        assert "忽略与原始议题无关的内容" in summary_prompt

    @pytest.mark.asyncio
    async def test_dynamic_word_limit_is_enforced_on_sent_messages(self, monkeypatch):
        """用户限制不同字数时，超限观点应由同一 Agent 后台重写为完整短答"""
        from agentmind.services.routing_service import _run_discussion
        from agentmind.routing.side_effects.session_registry import session_registry as _session

        agent_prompts = []

        async def _fake_send_20(text):
            sent_20.append(text)
            if text.startswith("【AgentA】"):
                _session.stop_discussion("u1")

        async def _fake_send_100(text):
            sent_100.append(text)
            if text.startswith("【AgentA】"):
                _session.stop_discussion("u1")

        async def _long_stream(msg):
            agent_prompts.append(msg)
            if "重写" in msg and "20字" in msg:
                yield StreamEvent(StreamEventType.CONTENT, "不必学AI，重游戏。")
                return
            if "重写" in msg and "100字" in msg:
                yield StreamEvent(StreamEventType.CONTENT, "幼儿园不必系统学AI，应重视游戏、表达、社交和真实互动。")
                return
            yield StreamEvent(
                StreamEventType.CONTENT,
                "幼儿园阶段应重视游戏、语言、社交、好奇心和真实互动，不应系统学习AI工具。"
                "如果过早把AI作为课程目标，容易把成人技术焦虑转嫁给儿童，削弱他们在现实世界中的探索、表达、合作和身体体验。"
                "教育重点应放在同伴协作、情绪管理、动手实验、身体运动和亲子阅读上，而不是提前训练工具使用。",
            )

        ex_a = _make_healthy_executor("a", "AgentA")
        ex_a.execute_stream = _long_stream
        ex_b = _make_healthy_executor("b", "AgentB")
        reg = _fake_registry({"a": ex_a, "b": ex_b})

        monkeypatch.setattr("agentmind.services.routing_service.record_task_start", AsyncMock())
        monkeypatch.setattr("agentmind.services.routing_service.record_task_end", AsyncMock())
        monkeypatch.setattr("agentmind.api.router.MemoryService", FakeDiscussionMemoryService)

        sent_20 = []
        _session.start_discussion("u1")
        await _run_discussion("幼儿园需要学习ai吗？回复限制20个字", ["a", "b"], "u1", reg, _fake_send_20)

        sent_100 = []
        _session.start_discussion("u1")
        await _run_discussion("幼儿园需要学习ai吗？回复限制100字", ["a", "b"], "u1", reg, _fake_send_100)

        agent_20 = next(msg for msg in sent_20 if msg.startswith("【AgentA】"))
        agent_100 = next(msg for msg in sent_100 if msg.startswith("【AgentA】"))
        content_20 = agent_20.split("\n", 1)[1]
        content_100 = agent_100.split("\n", 1)[1]
        assert len(content_20) <= 20
        assert len(content_100) <= 100
        assert len(content_100) > len(content_20)
        assert content_20 == "不必学AI，重游戏。"
        assert content_100 == "幼儿园不必系统学AI，应重视游戏、表达、社交和真实互动。"
        assert any("重写" in prompt and "20字" in prompt for prompt in agent_prompts)
        assert any("重写" in prompt and "100字" in prompt for prompt in agent_prompts)

    @pytest.mark.asyncio
    async def test_summary_word_limit_uses_background_rewrite(self, monkeypatch):
        """总结超限时也应后台重写，不应截断半句"""
        from agentmind.services.routing_service import _run_discussion
        from agentmind.routing.side_effects.session_registry import session_registry as _session

        sent_messages = []
        agent_prompts = []

        async def _fake_send(text):
            sent_messages.append(text)
            if text.startswith("【AgentA】"):
                _session.stop_discussion("u1")

        async def _agent_a_stream(msg):
            agent_prompts.append(msg)
            if "重写" in msg and "20字" in msg:
                yield StreamEvent(StreamEventType.CONTENT, "结论：不必学AI。")
                return
            if "讨论记录" in msg:
                yield StreamEvent(StreamEventType.CONTENT, "核心结论是幼儿园不必系统学习AI，应把重点放在游戏、表达和真实互动上。")
                return
            yield StreamEvent(StreamEventType.CONTENT, "不必学AI。")

        ex_a = _make_healthy_executor("a", "AgentA")
        ex_a.execute_stream = _agent_a_stream
        ex_b = _make_healthy_executor("b", "AgentB")
        reg = _fake_registry({"a": ex_a, "b": ex_b})

        monkeypatch.setattr("agentmind.services.routing_service.record_task_start", AsyncMock())
        monkeypatch.setattr("agentmind.services.routing_service.record_task_end", AsyncMock())
        monkeypatch.setattr("agentmind.api.router.MemoryService", FakeDiscussionMemoryService)

        _session.start_discussion("u1")
        await _run_discussion("幼儿园需要学习ai吗？回复限制20字", ["a", "b"], "u1", reg, _fake_send)

        summary = next(msg for msg in sent_messages if msg.startswith("总结（by AgentA）"))
        summary_content = summary.split("\n", 1)[1]
        assert summary_content == "结论：不必学AI。"
        assert len(summary_content) <= 20
        assert any("重写" in prompt and "20字" in prompt for prompt in agent_prompts)

    @pytest.mark.asyncio
    async def test_stop_discards_current_turn_but_keeps_final_summary(self, monkeypatch):
        """用户停在当前 Agent 流中时，应丢弃当前观点，但基于已完成历史输出总结"""
        from agentmind.services.routing_service import _run_discussion
        from agentmind.routing.side_effects.session_registry import session_registry as _session

        sent_messages = []
        agent_prompts = []

        async def _fake_send(text):
            sent_messages.append(text)

        async def _agent_a_stream(msg):
            agent_prompts.append(msg)
            yield StreamEvent(StreamEventType.CONTENT, "已完成观点")

        async def _agent_b_stream(msg):
            agent_prompts.append(msg)
            yield StreamEvent(StreamEventType.CONTENT, "当前轮半截观点")
            _session.stop_discussion("u1")
            yield StreamEvent(StreamEventType.CONTENT, "停后不应出现")

        ex_a = _make_healthy_executor("a", "AgentA")
        ex_a.execute_stream = _agent_a_stream
        ex_b = _make_healthy_executor("b", "AgentB")
        ex_b.execute_stream = _agent_b_stream
        reg = _fake_registry({"a": ex_a, "b": ex_b})

        monkeypatch.setattr("agentmind.services.routing_service.record_task_start", AsyncMock())
        monkeypatch.setattr("agentmind.services.routing_service.record_task_end", AsyncMock())
        monkeypatch.setattr("agentmind.api.router.MemoryService", FakeDiscussionMemoryService)

        _session.start_discussion("u1")
        await _run_discussion("幼儿园需要学习ai吗？回复限制50字", ["a", "b"], "u1", reg, _fake_send)

        assert any(msg.startswith("【AgentA】") for msg in sent_messages)
        assert not any(msg.startswith("【AgentB】") for msg in sent_messages)
        assert any(msg.startswith("总结（by AgentA）") for msg in sent_messages)
        summary_prompt = agent_prompts[-1]
        assert "已完成观点" in summary_prompt
        assert "当前轮半截观点" not in summary_prompt
        assert "停后不应出现" not in summary_prompt

    @pytest.mark.asyncio
    async def test_agent_stderr_error_shown(self, monkeypatch):
        """Agent stdout 为空但 stderr 有错误 → 显示错误原因"""
        from agentmind.services.routing_service import _run_discussion
        from agentmind.routing.side_effects.session_registry import session_registry as _session

        sent_messages = []

        async def _fake_send(text):
            sent_messages.append(text)
            if text.startswith("【Codex】"):
                _session.stop_discussion("u1")

        async def _error_stream(msg):
            yield StreamEvent(StreamEventType.ERROR, "Reconnecting... daemon not running")

        ex_a = _make_healthy_executor("codex", "Codex")
        ex_a.execute_stream = _error_stream
        ex_b = _make_healthy_executor("hermes", "Hermes")
        ex_b.execute_stream = _error_stream
        reg = _fake_registry({"codex": ex_a, "hermes": ex_b})

        monkeypatch.setattr("agentmind.services.routing_service.record_task_start", AsyncMock())
        monkeypatch.setattr("agentmind.services.routing_service.record_task_end", AsyncMock())
        monkeypatch.setattr("agentmind.api.router.MemoryService", FakeDiscussionMemoryService)

        _session.start_discussion("u1")
        await _run_discussion("测试", ["codex", "hermes"], "u1", reg, _fake_send)

        # 应该有包含错误信息的消息
        error_msgs = [m for m in sent_messages if "无输出" in m or "Reconnecting" in m]
        assert len(error_msgs) >= 1, f"未显示 stderr 错误，消息列表: {sent_messages[:3]}"

    @pytest.mark.asyncio
    async def test_stop_discussion_mid_stream(self, monkeypatch):
        """讨论中喊停 → Agent 流式输出被中断"""
        from agentmind.services.routing_service import _run_discussion
        from agentmind.routing.side_effects.session_registry import session_registry as _session

        sent_messages = []

        async def _fake_send(text):
            sent_messages.append(text)

        async def _long_stream(msg):
            yield StreamEvent(StreamEventType.CONTENT, "第一段")
            _session.stop_discussion("u1")
            yield StreamEvent(StreamEventType.CONTENT, "第二段不应出现")

        ex_a = _make_healthy_executor("a", "AgentA")
        ex_a.execute_stream = _long_stream
        ex_b = _make_healthy_executor("b", "AgentB")
        reg = _fake_registry({"a": ex_a, "b": ex_b})

        monkeypatch.setattr("agentmind.services.routing_service.record_task_start", AsyncMock())
        monkeypatch.setattr("agentmind.services.routing_service.record_task_end", AsyncMock())
        monkeypatch.setattr("agentmind.api.router.MemoryService", FakeDiscussionMemoryService)

        _session.start_discussion("u1")
        await _run_discussion("测试", ["a", "b"], "u1", reg, _fake_send)

        # 验证讨论在喊停后没有进入下一轮（不应有 AgentB 的发言）
        agent_b_speaks = [m for m in sent_messages if m.startswith("【AgentB】")]
        assert len(agent_b_speaks) == 0, f"喊停后不应有第二轮: {sent_messages}"


# ═══════════════════════════════════════
# 4. 讨论流程 SessionRegistry 集成
# ═══════════════════════════════════════

class TestDiscussionSessionIntegration:
    def test_start_stop_end_lifecycle(self):
        """讨论生命周期：start → check active → stop → end"""
        from agentmind.routing.side_effects.session_registry import SessionRegistry
        sr = SessionRegistry()

        sr.start_discussion("u1")
        assert sr.is_discussion_active("u1")

        sr.stop_discussion("u1")
        assert not sr.is_discussion_active("u1")

        sr.end_discussion("u1")
        assert "u1" not in sr._discussions
        assert not sr.is_discussion_active("u1")

    def test_list_discussions(self):
        """list_discussions 返回所有讨论"""
        from agentmind.routing.side_effects.session_registry import SessionRegistry
        sr = SessionRegistry()

        sr.start_discussion("u1")
        sr.start_discussion("u2")
        sr.stop_discussion("u2")

        discs = sr.list_discussions()
        assert "u1" in discs
        assert discs["u1"] == {"stop": False}
        assert discs["u2"] == {"stop": True}


# ═══════════════════════════════════════
# 5. extract_response_path 工具函数
# ═══════════════════════════════════════

class TestExtractResponsePath:
    def test_extracts_simple_path(self):
        from agentmind.routing.utils import extract_response_path
        result = extract_response_path(
            '{"payloads":[{"text":"hello"}]}', "payloads.0.text")
        assert result == "hello"

    def test_no_path_returns_original(self):
        from agentmind.routing.utils import extract_response_path
        result = extract_response_path("plain text", "")
        assert result == "plain text"

    def test_not_json_returns_original(self):
        from agentmind.routing.utils import extract_response_path
        result = extract_response_path("not json at all", "payloads.0.text")
        assert result == "not json at all"

    def test_invalid_path_returns_original(self):
        from agentmind.routing.utils import extract_response_path
        result = extract_response_path(
            '{"a":1}', "nonexistent.path")
        assert result == '{"a":1}'

    def test_nested_dict_path(self):
        from agentmind.routing.utils import extract_response_path
        result = extract_response_path(
            '{"data":{"result":"ok"}}', "data.result")
        assert result == "ok"


# ═══════════════════════════════════════
# Helpers
# ═══════════════════════════════════════

def _make_healthy_executor(aid, name, tags=None):
    cap = AgentCapability(
        id=aid, name=name, type="cli", tags=tags or ["general"],
        description=f"{name} agent", enabled=True, timeout=5,
    )
    from agentmind.agents.cli_executor import CLIExecutor
    ex = CLIExecutor(cap)
    ex.is_healthy = True
    ex.execute = AsyncMock(
        return_value=TaskResult(success=True, output=f"output from {aid}"))
    return ex


def _fake_registry(executors: dict):
    class _Reg:
        def __init__(self):
            self.executors = executors
        def get_executor(self, aid):
            return self.executors.get(aid)
    return _Reg()


def _fake_rule_engine():
    engine = MagicMock()
    engine.match = AsyncMock(return_value=None)
    engine.rules = []
    return engine


# ═══════════════════════════════════════
# Phase 8: 飞书路径 strategy_manager 集成
# ═══════════════════════════════════════

class TestPhase8FeishuStrategyManager:
    """阶段 8：飞书路径使用 strategy_manager 的测试。"""

    @pytest.mark.asyncio
    async def test_route_stream_passes_strategy_manager_to_pipeline(self, monkeypatch):
        """route_stream 将 strategy_manager 传递给 RoutingPipeline。"""
        from agentmind.api.router import route_stream

        ex = _make_healthy_executor("echo_agent", "Echo", tags=["general"])
        reg = _fake_registry({"echo_agent": ex})
        engine = _fake_rule_engine()
        settings = {"routing": {"use_new_pipeline": True}}

        from agentmind.services.strategy_manager import StrategyManager
        sm = StrategyManager(reg, engine)
        sm.set_enabled("semantic_intent", False)

        pipeline_sm_list = []

        class _CapturePipeline:
            def __init__(self, agent_registry, rule_engine, strategy_manager=None):
                pipeline_sm_list.append(strategy_manager)
                self._agent_registry = agent_registry
                self._rule_engine = rule_engine
                if strategy_manager is None:
                    from agentmind.services.strategy_manager import StrategyManager as SM
                    strategy_manager = SM(agent_registry, rule_engine)
                self._strategy_manager = strategy_manager

            async def run(self, msg, identity, settings, is_retry=False):
                from agentmind.routing.context import RoutingDecision, RoutingContext
                return RoutingDecision(
                    agent_id="echo_agent", strategy="signal_scoring",
                    confidence=1.0,
                    context=RoutingContext(
                        identity=identity, raw_message=msg,
                        candidates=["echo_agent"],
                    ),
                )

        monkeypatch.setattr(
            "agentmind.services.routing_service.RoutingPipeline",
            _CapturePipeline,
        )
        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_start", AsyncMock(),
        )
        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_update", AsyncMock(),
        )
        monkeypatch.setattr(
            "agentmind.routing.side_effects.trace_recorder.TraceRecorder.record_decision",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock(),
        )

        chunks = []
        async for chunk in route_stream(
            "写代码", "u1", reg, engine, settings,
            strategy_manager=sm,
        ):
            chunks.append(chunk)

        assert len(pipeline_sm_list) == 1, "应该创建 1 个 RoutingPipeline"
        captured = pipeline_sm_list[0]
        assert captured is sm, (
            f"route_stream 必须将 strategy_manager 传给 RoutingPipeline，"
            f"而不是创建新的默认实例"
        )

    @pytest.mark.asyncio
    async def test_route_stream_without_strategy_manager_creates_default(self, monkeypatch):
        """route_stream 不传 strategy_manager 时创建默认实例（回退兼容）。"""
        from agentmind.api.router import route_stream

        ex = _make_healthy_executor("echo_agent", "Echo", tags=["general"])
        reg = _fake_registry({"echo_agent": ex})
        engine = _fake_rule_engine()
        settings = {"routing": {"use_new_pipeline": True}}

        pipeline_sm_list = []

        class _CapturePipeline:
            def __init__(self, agent_registry, rule_engine, strategy_manager=None):
                pipeline_sm_list.append(strategy_manager)
                self._agent_registry = agent_registry
                self._rule_engine = rule_engine
                if strategy_manager is None:
                    from agentmind.services.strategy_manager import StrategyManager as SM
                    strategy_manager = SM(agent_registry, rule_engine)
                self._strategy_manager = strategy_manager

            async def run(self, msg, identity, settings, is_retry=False):
                from agentmind.routing.context import RoutingDecision, RoutingContext
                return RoutingDecision(
                    agent_id="echo_agent", strategy="signal_scoring",
                    confidence=1.0,
                    context=RoutingContext(
                        identity=identity, raw_message=msg,
                        candidates=["echo_agent"],
                    ),
                )

        monkeypatch.setattr(
            "agentmind.services.routing_service.RoutingPipeline",
            _CapturePipeline,
        )
        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_start", AsyncMock(),
        )
        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_update", AsyncMock(),
        )
        monkeypatch.setattr(
            "agentmind.routing.side_effects.trace_recorder.TraceRecorder.record_decision",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock(),
        )

        chunks = []
        async for chunk in route_stream(
            "写代码", "u1", reg, engine, settings,
            # 不传 strategy_manager
        ):
            chunks.append(chunk)

        assert len(pipeline_sm_list) == 1
        # 不传时创建默认的 StrategyManager 实例
        assert pipeline_sm_list[0] is None, (
            "不传 strategy_manager 时传 None，RoutingPipeline 内部创建默认"
        )

    @pytest.mark.asyncio
    async def test_disabled_strategy_affects_feishu_route_stream(self, monkeypatch):
        """禁用策略影响飞书 route_stream 的路由行为。"""
        from agentmind.api.router import route_stream

        ex = _make_healthy_executor("echo_agent", "Echo", tags=["general"])
        reg = _fake_registry({"echo_agent": ex})
        engine = _fake_rule_engine()
        settings = {"routing": {"use_new_pipeline": True}}

        from agentmind.services.strategy_manager import StrategyManager
        sm = StrategyManager(reg, engine)
        # 禁用 semantic_intent
        sm.set_enabled("semantic_intent", False)

        enabled_from_pipeline = []

        class _CapturePipeline:
            def __init__(self, agent_registry, rule_engine, strategy_manager=None):
                self._agent_registry = agent_registry
                self._rule_engine = rule_engine
                if strategy_manager is None:
                    from agentmind.services.strategy_manager import StrategyManager as SM
                    strategy_manager = SM(agent_registry, rule_engine)
                self._strategy_manager = strategy_manager

            async def run(self, msg, identity, settings, is_retry=False):
                enabled = self._strategy_manager.get_enabled_strategies(settings)
                for s in enabled:
                    enabled_from_pipeline.append(type(s).__name__)
                from agentmind.routing.context import RoutingDecision, RoutingContext
                return RoutingDecision(
                    agent_id="echo_agent", strategy="signal_scoring",
                    confidence=1.0,
                    context=RoutingContext(
                        identity=identity, raw_message=msg,
                        candidates=["echo_agent"],
                    ),
                )

        monkeypatch.setattr(
            "agentmind.services.routing_service.RoutingPipeline",
            _CapturePipeline,
        )
        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_start", AsyncMock(),
        )
        monkeypatch.setattr(
            "agentmind.services.routing_service.record_task_update", AsyncMock(),
        )
        monkeypatch.setattr(
            "agentmind.routing.side_effects.trace_recorder.TraceRecorder.record_decision",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock(),
        )

        chunks = []
        async for chunk in route_stream(
            "写代码", "u1", reg, engine, settings,
            strategy_manager=sm,
        ):
            chunks.append(chunk)

        assert "SemanticIntentStrategy" not in enabled_from_pipeline, (
            f"semantic_intent 已禁用，不应出现在飞书路径策略列表中: {enabled_from_pipeline}"
        )
        assert "SignalScoringStrategy" in enabled_from_pipeline, (
            "signal_scoring 必须仍然启用"
        )
