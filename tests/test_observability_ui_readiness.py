from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "observability-ui-readiness.md"
)
FINAL_CLOSEOUT_DOC = PROJECT_ROOT / "docs" / "architecture" / "final-closeout-status.md"
TASK_EVENT_CLOSEOUT_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-closeout-status.md"
)


REQUIRED_OBSERVABILITY_UI_READINESS_MARKERS = {
    "observability UI readiness",
    "future panel observability UI",
    "task replay timeline view",
    "must consume the existing panel replay endpoint",
    "`/panel/api/tasks/{trace_id}/replay`",
    "TaskReplayService",
    "must render the service DTO",
    "must not assemble timeline",
    "must not query TaskEventService",
    "must not call TaskTimelineService directly",
    "must not connect to stream queues",
    "must not reconstruct live SSE listener queues",
    "must not implement stream runtime replay",
    "must not create an API replay endpoint",
    "must not expand channel replay UX",
    "must not enable CPE or AgentShield enforcement",
    "must not inspect customer content",
    "read-only",
    "found and missing states",
    "bounded event display",
    "partial_output events may be displayed",
    "implementation requires a separate small package",
}


def _readiness_text() -> str:
    assert READINESS_DOC.exists(), (
        "docs/observability/observability-ui-readiness.md is required"
    )
    return READINESS_DOC.read_text(encoding="utf-8")


def test_observability_ui_readiness_document_exists_and_defers_ui():
    text = _readiness_text()

    assert "observability UI readiness" in text
    assert "implementation requires a separate small package" in text


def test_observability_ui_readiness_names_required_boundaries():
    text = _readiness_text()
    missing = sorted(
        marker
        for marker in REQUIRED_OBSERVABILITY_UI_READINESS_MARKERS
        if marker not in text
    )

    assert missing == []


def test_final_closeout_points_to_observability_ui_readiness():
    text = FINAL_CLOSEOUT_DOC.read_text(encoding="utf-8")

    assert "docs/observability/observability-ui-readiness.md" in text


def test_task_event_closeout_points_to_observability_ui_readiness():
    text = TASK_EVENT_CLOSEOUT_DOC.read_text(encoding="utf-8")

    assert "docs/observability/observability-ui-readiness.md" in text
