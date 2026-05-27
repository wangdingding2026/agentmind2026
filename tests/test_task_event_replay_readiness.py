from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPLAY_READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-replay-readiness.md"
)
TASK_EVENT_READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-readiness.md"
)


REQUIRED_REPLAY_READINESS_MARKERS = {
    "task-event replay readiness",
    "future persistent task-event replay",
    "TaskEventService owns stored task timeline events",
    "TaskTimelineService remains the read-side DTO boundary",
    "Replay must use persisted task timeline events",
    "Replay must not reconstruct live SSE listener queues",
    "stream_snapshot remains an in-process backlog boundary",
    "future TaskReplayService",
    "service-level boundary before panel/API/channel adapters",
    "no observability UI",
    "no stream runtime behavior changes",
    "no panel/API/channel replay assembly",
    "no CPE or AgentShield enforcement",
    "no customer-content inspection",
}


def _replay_readiness_text() -> str:
    assert REPLAY_READINESS_DOC.exists(), (
        "docs/observability/task-event-replay-readiness.md is required"
    )
    return REPLAY_READINESS_DOC.read_text(encoding="utf-8")


def test_task_event_replay_readiness_document_exists_and_defers_replay():
    text = _replay_readiness_text()

    assert "task-event replay readiness" in text
    assert "future persistent task-event replay" in text
    assert "not implemented in this package" in text


def test_task_event_replay_readiness_document_names_required_boundaries():
    text = _replay_readiness_text()
    missing = sorted(
        marker for marker in REQUIRED_REPLAY_READINESS_MARKERS if marker not in text
    )

    assert missing == []


def test_task_event_readiness_points_to_replay_readiness_gate():
    text = TASK_EVENT_READINESS_DOC.read_text(encoding="utf-8")

    assert "docs/observability/task-event-replay-readiness.md" in text
