import pytest


class _SessionRegistry:
    def __init__(self):
        self.registered = []
        self.unregistered = []
        self.queue = None

    def list_discussions(self):
        return {
            "u1": {"stop": False},
            "u2": {"stop": True},
        }

    def register_stream_listener(self, trace_id):
        import asyncio

        self.registered.append(trace_id)
        self.queue = asyncio.Queue()
        return self.queue

    def unregister_stream_listener(self, trace_id, queue):
        self.unregistered.append((trace_id, queue))


class _TaskService:
    def __init__(self):
        self.calls = []

    async def query_tasks(self, **kwargs):
        self.calls.append(kwargs)
        return [{"trace_id": "t1", "status": "executing"}]


class _AttachRegistry:
    def __init__(self):
        self.bindings = []

    def bind(self, session_id, trace_id):
        self.bindings.append((session_id, trace_id))


@pytest.mark.asyncio
async def test_session_runtime_service_builds_active_sessions_view():
    from agentmind.services.session_runtime_service import SessionRuntimeService

    task_service = _TaskService()
    result = await SessionRuntimeService(
        session_registry=_SessionRegistry(),
        task_service=task_service,
    ).active_sessions()

    assert result == {
        "discussions": [
            {"user_id": "u1", "stop": False},
            {"user_id": "u2", "stop": True},
        ],
        "executing_tasks": [{"trace_id": "t1", "status": "executing"}],
    }
    assert task_service.calls == [{"limit": 5, "status": "executing"}]


def test_session_runtime_service_attach_requires_session_id():
    from agentmind.services.session_runtime_service import SessionRuntimeService

    result = SessionRuntimeService(
        session_registry=_SessionRegistry(),
        task_service=_TaskService(),
        attach_registry=_AttachRegistry(),
    ).attach_to_task("t1", "")

    assert result == {"error": "缺少 session_id 参数"}


def test_session_runtime_service_attach_requires_registry():
    from agentmind.services.session_runtime_service import SessionRuntimeService

    result = SessionRuntimeService(
        session_registry=_SessionRegistry(),
        task_service=_TaskService(),
        attach_registry=None,
    ).attach_to_task("t1", "s1")

    assert result == {"error": "Attach 功能未启用"}


def test_session_runtime_service_attach_binds_session_to_trace():
    from agentmind.services.session_runtime_service import SessionRuntimeService

    attach_registry = _AttachRegistry()
    result = SessionRuntimeService(
        session_registry=_SessionRegistry(),
        task_service=_TaskService(),
        attach_registry=attach_registry,
    ).attach_to_task("t1", "s1")

    assert result == {"status": "attached", "trace_id": "t1"}
    assert attach_registry.bindings == [("s1", "t1")]


def test_session_registry_persists_discussion_lifecycle_to_runtime_store():
    from agentmind.routing.side_effects.session_registry import SessionRegistry

    class Store:
        def __init__(self):
            self.upserts = []
            self.deletes = []

        def upsert_discussion(self, user_id, stop):
            self.upserts.append((user_id, stop))

        def delete_discussion(self, user_id):
            self.deletes.append(user_id)

    store = Store()
    registry = SessionRegistry(runtime_store=store)

    registry.start_discussion("u1")
    registry.stop_discussion("u1")
    registry.end_discussion("u1")

    assert store.upserts == [("u1", False), ("u1", True)]
    assert store.deletes == ["u1"]


def test_session_runtime_service_restores_persisted_discussions():
    from agentmind.services.session_runtime_service import SessionRuntimeService

    class Registry:
        def __init__(self):
            self.restored = None

        def restore_discussions(self, discussions):
            self.restored = discussions

    class Store:
        def list_discussions(self):
            return {
                "u1": {"stop": False},
                "u2": {"stop": True},
            }

        def list_attach_bindings(self):
            return {}

    registry = Registry()
    result = SessionRuntimeService(
        session_registry=registry,
        task_service=_TaskService(),
        runtime_store=Store(),
    ).restore_runtime_state()

    assert result == {"restored_discussions": 2, "restored_attach_bindings": 0}
    assert registry.restored == {
        "u1": {"stop": False},
        "u2": {"stop": True},
    }


def test_session_runtime_service_restores_persisted_attach_bindings():
    from agentmind.services.session_runtime_service import SessionRuntimeService

    class Registry:
        def restore_discussions(self, discussions):
            pass

    class AttachRegistry:
        def __init__(self):
            self.restored = None

        def restore_bindings(self, bindings):
            self.restored = bindings

    class Store:
        def list_discussions(self):
            return {}

        def list_attach_bindings(self):
            return {"s1": "t1", "s2": "t2"}

    attach_registry = AttachRegistry()
    result = SessionRuntimeService(
        session_registry=Registry(),
        task_service=_TaskService(),
        attach_registry=attach_registry,
        runtime_store=Store(),
    ).restore_runtime_state()

    assert result == {"restored_discussions": 0, "restored_attach_bindings": 2}
    assert attach_registry.restored == {"s1": "t1", "s2": "t2"}


def test_default_session_registry_has_runtime_store():
    from agentmind.routing.side_effects.session_registry import session_registry

    assert getattr(session_registry, "_runtime_store", None) is not None


@pytest.mark.asyncio
async def test_session_runtime_service_stream_events_unregisters_listener():
    import asyncio

    from agentmind.services.session_runtime_service import SessionRuntimeService

    session_registry = _SessionRegistry()
    service = SessionRuntimeService(
        session_registry=session_registry,
        task_service=_TaskService(),
    )

    async def collect_events():
        received = []
        async for event in service.stream_events("t1"):
            received.append(event)
        return received

    task = asyncio.create_task(collect_events())
    await asyncio.sleep(0)
    await session_registry.queue.put({"event": "partial", "data": "hello"})
    await session_registry.queue.put(None)

    received = await task

    assert received == [{"event": "partial", "data": "hello"}]
    assert session_registry.registered == ["t1"]
    assert session_registry.unregistered == [("t1", session_registry.queue)]
