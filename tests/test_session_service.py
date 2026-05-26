import pytest


@pytest.mark.asyncio
async def test_session_service_new_session_persists_force_flag_and_clears_working_memory():
    from agentmind.services.session_service import SessionService

    svc = SessionService()
    svc.add_to_working_memory("u1", "user", "hello")
    svc.add_to_working_memory("u1", "assistant", "world")
    assert svc.get_working_memory("u1", limit=1)

    sid = await svc.new_session("u1")

    assert sid.startswith("sess-")
    assert svc.get_active_session("u1") == sid
    assert svc.get_working_memory("u1", limit=1) == []
    assert svc.consume_force_new("u1") is True
    assert svc.consume_force_new("u1") is False

    restarted = SessionService()
    assert restarted.get_active_session("u1") == sid


def test_session_service_recovers_working_memory_after_new_instance():
    from agentmind.services.session_service import SessionService

    svc = SessionService()
    svc.add_to_working_memory("u1", "user", "first")
    svc.add_to_working_memory("u1", "assistant", "reply")

    restarted = SessionService()
    rounds = restarted.get_working_memory("u1", limit=1)

    assert len(rounds) == 1
    assert rounds[0]["user"] == "first"
    assert rounds[0]["assistant"] == "reply"
    assert rounds[0]["ts"]


def test_session_service_reads_active_conversation_id():
    from agentmind.services.session_service import SessionService

    svc = SessionService()
    conn = svc._store._get_conn()
    try:
        conn.execute(
            """INSERT INTO conversations
               (conversation_id, user_id, first_message_at, last_message_at, status)
               VALUES (?, ?, ?, ?, ?)""",
            ("conv-active-boundary", "u1", "2026-05-25 09:00:00", "2026-05-25 10:00:00", "active"),
        )
        conn.execute(
            """INSERT INTO conversations
               (conversation_id, user_id, first_message_at, last_message_at, status)
               VALUES (?, ?, ?, ?, ?)""",
            ("conv-closed-boundary", "u1", "2026-05-24 09:00:00", "2026-05-24 10:00:00", "closed"),
        )
        conn.commit()
    finally:
        conn.close()

    assert svc.get_active_conversation_id("u1") == "conv-active-boundary"


@pytest.mark.asyncio
async def test_memory_service_uses_session_service_force_new_flag(monkeypatch):
    from agentmind.memory import service as memory_service

    calls = []

    class FakeSessionService:
        def __init__(self, store=None):
            pass

        def consume_force_new(self, user_id):
            calls.append(("consume", user_id))
            return True

        def ensure_active_session(self, user_id):
            calls.append(("ensure", user_id))
            return "sess-existing", False

    class FakeWritePipeline:
        def __init__(self, store):
            pass

        async def execute(self, mem, force_new_conversation=False):
            calls.append(("force", force_new_conversation))
            return [mem.memory_id]

    monkeypatch.setattr(memory_service, "SessionService", FakeSessionService)
    monkeypatch.setattr(
        "agentmind.memory.pipeline.write_pipeline.WritePipeline",
        FakeWritePipeline,
    )

    svc = memory_service.MemoryService(store=object())

    assert await svc.write_memory({"memory_id": "m1", "content": "hello", "user_id": "u1"}) == 1
    assert ("consume", "u1") in calls
    assert ("force", True) in calls


def test_memory_service_working_memory_delegates_to_session_service(monkeypatch):
    from agentmind.memory import service as memory_service

    calls = []

    class FakeSessionService:
        def __init__(self, store=None):
            pass

        def add_to_working_memory(self, user_id, role, content):
            calls.append(("add", user_id, role, content))

        def get_working_memory(self, user_id, limit=3):
            calls.append(("get", user_id, limit))
            return [{"user": "hello", "assistant": "world", "ts": "now"}]

    monkeypatch.setattr(memory_service, "SessionService", FakeSessionService)

    svc = memory_service.MemoryService(store=object())
    svc.add_to_working_memory("u1", "user", "hello")

    assert svc.get_working_memory("u1", limit=1) == [
        {"user": "hello", "assistant": "world", "ts": "now"}
    ]
    assert ("add", "u1", "user", "hello") in calls
    assert ("get", "u1", 1) in calls
