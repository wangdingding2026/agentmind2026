from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-replay-adapter-readiness.md"
)
REPLAY_READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-replay-readiness.md"
)


REQUIRED_ADAPTER_READINESS_MARKERS = {
    "read-only TaskReplay adapter readiness",
    "TaskReplayService service contract already exists",
    "service-level replay DTO boundary",
    "The panel has a read-only replay endpoint backed by TaskReplayService",
    "API and channel currently have no replay endpoint",
    "The panel `task_replay` handler calls TaskReplayService",
    "future read-only adapter must call TaskReplayService",
    "must not assemble timeline",
    "must not query TaskEventService",
    "must not connect to stream queues",
    "adapter DTO must pass through the service DTO",
    "does not implement stream runtime replay",
    "does not implement observability UI",
    "does not enable CPE or AgentShield enforcement",
    "does not inspect customer content",
    "endpoint implementation requires a separate small package",
}


def _adapter_readiness_text() -> str:
    assert ADAPTER_READINESS_DOC.exists(), (
        "docs/observability/task-replay-adapter-readiness.md is required"
    )
    return ADAPTER_READINESS_DOC.read_text(encoding="utf-8")


def test_task_replay_adapter_readiness_document_exists_and_defers_endpoint():
    text = _adapter_readiness_text()

    assert "read-only TaskReplay adapter readiness" in text
    assert "The read-only panel replay endpoint is implemented" in text
    assert "Additional endpoint implementation requires a separate small package" in text


def test_task_replay_adapter_readiness_document_names_required_boundaries():
    text = _adapter_readiness_text()
    missing = sorted(
        marker for marker in REQUIRED_ADAPTER_READINESS_MARKERS if marker not in text
    )

    assert missing == []


def test_task_event_replay_readiness_points_to_adapter_readiness_gate():
    text = REPLAY_READINESS_DOC.read_text(encoding="utf-8")

    assert "docs/observability/task-replay-adapter-readiness.md" in text
