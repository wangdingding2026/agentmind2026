from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
READINESS_DOC = PROJECT_ROOT / "docs" / "observability" / "task-event-readiness.md"
PHASE5_CLOSURE_DOC = PROJECT_ROOT / "docs" / "phase5" / "phase-5-closure-status.md"


REQUIRED_TASK_EVENT_READINESS_MARKERS = {
    "task-event observability readiness",
    "persistent task-event replay",
    "later package",
    "TaskService owns task lifecycle state",
    "TraceService owns routing traces",
    "AuditService owns audit events",
    "TaskEventService owns ordered task timeline events",
    "task_started",
    "routing_started",
    "agent_selected",
    "execution_started",
    "partial_output",
    "completed",
    "failed",
    "stream_snapshot remains in-process backlog only",
    "live SSE listener queues are not persisted or restored",
    "panel/API/channel remain adapters",
    "no observability UI",
    "no CPE or AgentShield enforcement",
}


def _readiness_text() -> str:
    assert READINESS_DOC.exists(), (
        "docs/observability/task-event-readiness.md is required"
    )
    return READINESS_DOC.read_text(encoding="utf-8")


def test_task_event_readiness_document_exists_and_defers_replay():
    text = _readiness_text()

    assert "task-event observability readiness" in text
    assert "persistent task-event replay" in text
    assert "later package" in text


def test_task_event_readiness_document_names_required_boundaries():
    text = _readiness_text()
    missing = sorted(
        marker for marker in REQUIRED_TASK_EVENT_READINESS_MARKERS if marker not in text
    )

    assert missing == []


def test_phase5_closure_points_to_task_event_readiness():
    text = PHASE5_CLOSURE_DOC.read_text(encoding="utf-8")

    assert "docs/observability/task-event-readiness.md" in text
