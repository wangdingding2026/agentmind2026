from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLOSEOUT_DOC = PROJECT_ROOT / "docs" / "observability" / "task-event-closeout-status.md"
TASK_EVENT_READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-readiness.md"
)
REPLAY_READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-replay-readiness.md"
)
ADAPTER_READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-replay-adapter-readiness.md"
)


REQUIRED_CLOSEOUT_MARKERS = {
    "observability/task-event route is closed",
    "TaskEventService owns stored task timeline events",
    "TaskService produces lifecycle task events",
    "TaskService produces `partial_output` task events",
    "TaskTimelineService owns read-side timeline DTO assembly",
    "TaskExplanationService includes timeline data through TaskTimelineService",
    "TaskReplayService owns the service-level replay DTO boundary",
    "panel `task_replay` handler calls TaskReplayService",
    "panel/API/channel remain adapters",
    "stream_snapshot remains in-process backlog only",
    "live SSE listener queues are not persisted or restored",
    "Replay uses persisted task timeline events",
    "does not reconstruct live SSE listener queues",
    "no API replay endpoint",
    "no channel replay adapter",
    "no observability UI",
    "no stream runtime replay",
    "no CPE or AgentShield enforcement",
    "no customer-content inspection",
    "no TaskEventService schema change",
    "no TaskTimelineService ordering or query change",
    "no SessionRuntimeService change",
    "no `feishu.route_callback` migration expansion",
}


def _closeout_text() -> str:
    assert CLOSEOUT_DOC.exists(), (
        "docs/observability/task-event-closeout-status.md is required"
    )
    return CLOSEOUT_DOC.read_text(encoding="utf-8")


def test_task_event_closeout_document_exists_and_declares_closed():
    text = _closeout_text()

    assert "observability/task-event route is closed" in text
    assert "closeout decision" in text


def test_task_event_closeout_document_names_required_boundaries():
    text = _closeout_text()
    missing = sorted(marker for marker in REQUIRED_CLOSEOUT_MARKERS if marker not in text)

    assert missing == []


def test_task_event_readiness_points_to_closeout_status():
    text = TASK_EVENT_READINESS_DOC.read_text(encoding="utf-8")

    assert "docs/observability/task-event-closeout-status.md" in text


def test_task_event_replay_readiness_points_to_closeout_status():
    text = REPLAY_READINESS_DOC.read_text(encoding="utf-8")

    assert "docs/observability/task-event-closeout-status.md" in text


def test_task_replay_adapter_readiness_points_to_closeout_status():
    text = ADAPTER_READINESS_DOC.read_text(encoding="utf-8")

    assert "docs/observability/task-event-closeout-status.md" in text
