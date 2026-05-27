"""会话注册表：统一管理流监听、讨论状态。

从 api/router.py 的全局字典迁移而来，模块级单例。
"""

import asyncio
import time


class SessionRegistry:
    """流监听 + 讨论状态的统一注册表。"""

    def __init__(self, runtime_store=None):
        self._streams: dict[str, dict] = {}
        self._discussions: dict[str, dict] = {}
        self._runtime_store = runtime_store

    # ── 流监听 ──

    def register_stream_listener(self, trace_id: str) -> asyncio.Queue:
        if trace_id not in self._streams:
            self._streams[trace_id] = {"listeners": [], "backlog": [], "created_at": time.time()}
        queue = asyncio.Queue(maxsize=100)
        registry = self._streams[trace_id]
        registry["listeners"].append(queue)
        for chunk in registry["backlog"][-50:]:
            try:
                queue.put_nowait(chunk)
            except asyncio.QueueFull:
                break
        return queue

    def unregister_stream_listener(self, trace_id: str, queue: asyncio.Queue):
        if trace_id not in self._streams:
            return
        registry = self._streams[trace_id]
        if queue in registry["listeners"]:
            registry["listeners"].remove(queue)
        if not registry["listeners"]:
            del self._streams[trace_id]

    def broadcast_stream_chunk(self, trace_id: str, chunk: dict):
        if trace_id not in self._streams:
            self._streams[trace_id] = {"listeners": [], "backlog": [], "created_at": time.time()}
        registry = self._streams[trace_id]
        registry["backlog"].append(chunk)
        if len(registry["backlog"]) > 50:
            registry["backlog"] = registry["backlog"][-50:]
        dead = []
        for q in registry["listeners"]:
            try:
                q.put_nowait(chunk)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.unregister_stream_listener(trace_id, q)

    def cleanup_stale_streams(self, ttl_seconds: int = 600) -> int:
        now = time.time()
        stale = []
        for trace_id, registry in self._streams.items():
            if not registry["listeners"] and now - registry.get("created_at", now) > ttl_seconds:
                stale.append(trace_id)
        for trace_id in stale:
            del self._streams[trace_id]
        return len(stale)

    def stream_snapshot(self, trace_id: str) -> dict:
        registry = self._streams.get(trace_id)
        if not registry:
            return {
                "trace_id": trace_id,
                "backlog": [],
                "listener_count": 0,
                "resumable": False,
            }
        backlog = list(registry.get("backlog", []))
        return {
            "trace_id": trace_id,
            "backlog": backlog,
            "listener_count": len(registry.get("listeners", [])),
            "resumable": bool(backlog),
        }

    # ── 讨论状态 ──

    def start_discussion(self, user_id: str):
        self._discussions[user_id] = {"stop": False}
        if self._runtime_store is not None:
            self._runtime_store.upsert_discussion(user_id, stop=False)

    def stop_discussion(self, user_id: str):
        disc = self._discussions.get(user_id)
        if disc:
            disc["stop"] = True
            if self._runtime_store is not None:
                self._runtime_store.upsert_discussion(user_id, stop=True)

    def is_discussion_active(self, user_id: str) -> bool:
        disc = self._discussions.get(user_id)
        return bool(disc and not disc.get("stop"))

    def end_discussion(self, user_id: str):
        self._discussions.pop(user_id, None)
        if self._runtime_store is not None:
            self._runtime_store.delete_discussion(user_id)

    def list_discussions(self) -> dict[str, dict]:
        return dict(self._discussions)

    def restore_discussions(self, discussions: dict[str, dict]):
        self._streams = {}
        self._discussions = {
            str(user_id): {"stop": bool(discussion.get("stop", False))}
            for user_id, discussion in discussions.items()
        }


def _default_runtime_store():
    from agentmind.services.session_runtime_store import SessionRuntimeStore

    return SessionRuntimeStore()


# 模块级单例
session_registry = SessionRegistry(runtime_store=_default_runtime_store())
