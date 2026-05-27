"""Peek 流广播测试"""
import asyncio

import pytest


class TestStreamRegistry:
    def test_register_and_broadcast(self):
        from agentmind.routing.side_effects.session_registry import SessionRegistry

        sr = SessionRegistry()

        q1 = sr.register_stream_listener("tr-test")
        assert "tr-test" in sr._streams
        assert len(sr._streams["tr-test"]["listeners"]) == 1

        chunk = {"event": "partial", "data": '{"content":"hello"}'}
        sr.broadcast_stream_chunk("tr-test", chunk)

        received = q1.get_nowait()
        assert received == chunk

        sr.unregister_stream_listener("tr-test", q1)
        assert "tr-test" not in sr._streams

    def test_backlog_replay(self):
        from agentmind.routing.side_effects.session_registry import SessionRegistry

        sr = SessionRegistry()

        for i in range(3):
            sr.broadcast_stream_chunk("tr-backlog", {"event": "partial", "data": f'"{i}"'})

        q = sr.register_stream_listener("tr-backlog")
        backlog = []
        while not q.empty():
            backlog.append(q.get_nowait())
        assert len(backlog) == 3

        sr.unregister_stream_listener("tr-backlog", q)

    def test_queue_full_drops_listener(self):
        from agentmind.routing.side_effects.session_registry import SessionRegistry

        sr = SessionRegistry()

        q = sr.register_stream_listener("tr-full")
        for i in range(100):
            q.put_nowait({"event": "partial", "data": f'"{i}"'})

        sr.broadcast_stream_chunk("tr-full", {"event": "partial", "data": '"overflow"'})
        assert "tr-full" not in sr._streams

    def test_stream_backlog_is_not_restored_with_discussions(self):
        from agentmind.routing.side_effects.session_registry import SessionRegistry

        sr = SessionRegistry()
        sr.broadcast_stream_chunk("tr-backlog", {"event": "partial", "data": "hello"})
        assert "tr-backlog" in sr._streams

        sr.restore_discussions({"u1": {"stop": False}})

        assert sr.list_discussions() == {"u1": {"stop": False}}
        assert sr._streams == {}

    def test_stream_snapshot_returns_backlog_without_registering_listener(self):
        from agentmind.routing.side_effects.session_registry import SessionRegistry

        sr = SessionRegistry()
        sr.broadcast_stream_chunk("tr-snap", {"event": "partial", "data": "one"})
        sr.broadcast_stream_chunk("tr-snap", {"event": "partial", "data": "two"})

        snapshot = sr.stream_snapshot("tr-snap")

        assert snapshot == {
            "trace_id": "tr-snap",
            "backlog": [
                {"event": "partial", "data": "one"},
                {"event": "partial", "data": "two"},
            ],
            "listener_count": 0,
            "resumable": True,
        }
        assert sr._streams["tr-snap"]["listeners"] == []

    def test_stream_snapshot_for_missing_trace_is_not_resumable(self):
        from agentmind.routing.side_effects.session_registry import SessionRegistry

        sr = SessionRegistry()

        assert sr.stream_snapshot("missing") == {
            "trace_id": "missing",
            "backlog": [],
            "listener_count": 0,
            "resumable": False,
        }

    def test_stream_snapshot_is_not_restored_after_runtime_restore(self):
        from agentmind.routing.side_effects.session_registry import SessionRegistry

        sr = SessionRegistry()
        sr.broadcast_stream_chunk("tr-backlog", {"event": "partial", "data": "hello"})

        sr.restore_discussions({"u1": {"stop": False}})

        assert sr.stream_snapshot("tr-backlog") == {
            "trace_id": "tr-backlog",
            "backlog": [],
            "listener_count": 0,
            "resumable": False,
        }
