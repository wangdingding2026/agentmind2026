"""Core LLM Provider 测试 — core_llm_chat, extract_atomic_facts"""
import asyncio
import json
import tempfile
from pathlib import Path

import pytest
import yaml as _yaml

from agentmind.core import core_llm


@pytest.fixture
def tmp_core_llm_cfg():
    """临时 core_llm 配置环境"""
    mp = pytest.MonkeyPatch()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        config_dir = tmp_dir / "config"
        config_dir.mkdir(parents=True)
        mp.setattr(core_llm, "CONFIG_DIR", config_dir)
        yield config_dir
    mp.undo()


class TestCoreLLMChat:
    """core_llm_chat() 基础调用测试"""

    def test_disabled_returns_none(self, tmp_core_llm_cfg):
        """未启用时返回 None"""
        (tmp_core_llm_cfg / "settings.yaml").write_text(
            _yaml.dump({"core_llm": {"enabled": False}}), encoding="utf-8"
        )
        result = asyncio.run(core_llm.core_llm_chat([{"role": "user", "content": "hello"}]))
        assert result is None

    def test_no_endpoint_returns_none(self, tmp_core_llm_cfg):
        """无 endpoint 时返回 None"""
        (tmp_core_llm_cfg / "settings.yaml").write_text(
            _yaml.dump({"core_llm": {"enabled": True, "endpoint": ""}}), encoding="utf-8"
        )
        result = asyncio.run(core_llm.core_llm_chat([{"role": "user", "content": "hello"}]))
        assert result is None

    def test_successful_call(self, tmp_core_llm_cfg, monkeypatch):
        """API 调用成功返回内容"""
        (tmp_core_llm_cfg / "settings.yaml").write_text(
            _yaml.dump({
                "core_llm": {
                    "enabled": True,
                    "endpoint": "https://api.example.com/chat",
                    "api_key": "sk-test",
                    "model": "test-model",
                    "timeout_seconds": 5,
                }
            }), encoding="utf-8"
        )

        class MockResp:
            status_code = 200
            def json(self):
                return {"choices": [{"message": {"content": "你好！我是 AgentMind。"}}]}

        class MockClient:
            def __init__(self, *a, **kw):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass
            async def post(self, *a, **kw):
                return MockResp()

        monkeypatch.setattr(core_llm.httpx, "AsyncClient", MockClient)
        result = asyncio.run(core_llm.core_llm_chat([{"role": "user", "content": "你好"}]))
        assert result == "你好！我是 AgentMind。"

    def test_api_error_returns_none(self, tmp_core_llm_cfg, monkeypatch):
        """API 错误时静默返回 None"""
        (tmp_core_llm_cfg / "settings.yaml").write_text(
            _yaml.dump({
                "core_llm": {
                    "enabled": True,
                    "endpoint": "https://api.example.com/chat",
                    "api_key": "sk-test",
                    "model": "test-model",
                }
            }), encoding="utf-8"
        )

        class MockClient:
            def __init__(self, *a, **kw):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass
            async def post(self, *a, **kw):
                raise ConnectionError("timeout")

        monkeypatch.setattr(core_llm.httpx, "AsyncClient", MockClient)
        result = asyncio.run(core_llm.core_llm_chat([{"role": "user", "content": "hello"}]))
        assert result is None


class TestExtractAtomicFacts:
    """extract_atomic_facts() 测试"""

    def test_extract_knowledge(self, tmp_core_llm_cfg, monkeypatch):
        """提取知识类型事实"""
        (tmp_core_llm_cfg / "settings.yaml").write_text(
            _yaml.dump({
                "core_llm": {"enabled": True, "endpoint": "https://api.example.com/chat",
                         "api_key": "sk-test", "model": "test"}
            }), encoding="utf-8"
        )

        class MockResp:
            status_code = 200
            def json(self):
                return {"choices": [{"message": {"content": json.dumps({
                    "facts": [{"fact": "Python GIL 是全局解释器锁", "type": "knowledge"}]
                })}}]}

        class MockClient:
            def __init__(self, *a, **kw):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass
            async def post(self, *a, **kw):
                return MockResp()

        monkeypatch.setattr(core_llm.httpx, "AsyncClient", MockClient)
        facts = asyncio.run(core_llm.extract_atomic_facts("什么是 GIL", "GIL 是全局解释器锁..."))
        assert facts is not None
        assert len(facts) == 1
        assert facts[0]["type"] == "knowledge"
        assert "GIL" in facts[0]["fact"]

    def test_extract_preference(self, tmp_core_llm_cfg, monkeypatch):
        """提取偏好类型事实"""
        (tmp_core_llm_cfg / "settings.yaml").write_text(
            _yaml.dump({
                "core_llm": {"enabled": True, "endpoint": "https://api.example.com/chat",
                         "api_key": "sk-test", "model": "test"}
            }), encoding="utf-8"
        )

        class MockResp:
            status_code = 200
            def json(self):
                return {"choices": [{"message": {"content": json.dumps({
                    "facts": [{"fact": "用户偏好使用中文交流", "type": "preference"}]
                })}}]}

        class MockClient:
            def __init__(self, *a, **kw):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass
            async def post(self, *a, **kw):
                return MockResp()

        monkeypatch.setattr(core_llm.httpx, "AsyncClient", MockClient)
        facts = asyncio.run(core_llm.extract_atomic_facts("用中文回答", "好的，我会用中文"))
        assert facts is not None
        assert facts[0]["type"] == "preference"

    def test_empty_facts(self, tmp_core_llm_cfg, monkeypatch):
        """对话无可提取事实时返回空列表"""
        (tmp_core_llm_cfg / "settings.yaml").write_text(
            _yaml.dump({
                "core_llm": {"enabled": True, "endpoint": "https://api.example.com/chat",
                         "api_key": "sk-test", "model": "test"}
            }), encoding="utf-8"
        )

        class MockResp:
            status_code = 200
            def json(self):
                return {"choices": [{"message": {"content": '{"facts": []}'}}]}

        class MockClient:
            def __init__(self, *a, **kw):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass
            async def post(self, *a, **kw):
                return MockResp()

        monkeypatch.setattr(core_llm.httpx, "AsyncClient", MockClient)
        facts = asyncio.run(core_llm.extract_atomic_facts("你好", "你好！"))
        assert facts == []

    def test_invalid_json_returns_none(self, tmp_core_llm_cfg, monkeypatch):
        """LLM 返回非法 JSON 时返回 None"""
        (tmp_core_llm_cfg / "settings.yaml").write_text(
            _yaml.dump({
                "core_llm": {"enabled": True, "endpoint": "https://api.example.com/chat",
                         "api_key": "sk-test", "model": "test"}
            }), encoding="utf-8"
        )

        class MockResp:
            status_code = 200
            def json(self):
                return {"choices": [{"message": {"content": "not valid json {{{"}}]}

        class MockClient:
            def __init__(self, *a, **kw):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass
            async def post(self, *a, **kw):
                return MockResp()

        monkeypatch.setattr(core_llm.httpx, "AsyncClient", MockClient)
        facts = asyncio.run(core_llm.extract_atomic_facts("hello", "world"))
        assert facts is None

    def test_api_error_returns_none(self, tmp_core_llm_cfg, monkeypatch):
        """API 调用失败时 extract 返回 None"""
        (tmp_core_llm_cfg / "settings.yaml").write_text(
            _yaml.dump({
                "core_llm": {"enabled": True, "endpoint": "https://api.example.com/chat",
                         "api_key": "sk-test", "model": "test"}
            }), encoding="utf-8"
        )

        class MockClient:
            def __init__(self, *a, **kw):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass
            async def post(self, *a, **kw):
                raise ConnectionError("timeout")

        monkeypatch.setattr(core_llm.httpx, "AsyncClient", MockClient)
        facts = asyncio.run(core_llm.extract_atomic_facts("hello", "world"))
        assert facts is None

    def test_markdown_code_block_json(self, tmp_core_llm_cfg, monkeypatch):
        """处理 LLM 返回 markdown 代码块包裹的 JSON"""
        (tmp_core_llm_cfg / "settings.yaml").write_text(
            _yaml.dump({
                "core_llm": {"enabled": True, "endpoint": "https://api.example.com/chat",
                         "api_key": "sk-test", "model": "test"}
            }), encoding="utf-8"
        )

        class MockResp:
            status_code = 200
            def json(self):
                return {"choices": [{"message": {"content": '```json\n{"facts": [{"fact": "test", "type": "knowledge"}]}\n```'}}]}

        class MockClient:
            def __init__(self, *a, **kw):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass
            async def post(self, *a, **kw):
                return MockResp()

        monkeypatch.setattr(core_llm.httpx, "AsyncClient", MockClient)
        facts = asyncio.run(core_llm.extract_atomic_facts("hello", "world"))
        assert facts is not None
        assert len(facts) == 1
        assert facts[0]["fact"] == "test"
