from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "channel-replay-adapter-readiness.md"
)
FINAL_CLOSEOUT_DOC = PROJECT_ROOT / "docs" / "architecture" / "final-closeout-status.md"
TASK_EVENT_CLOSEOUT_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-closeout-status.md"
)


REQUIRED_CHANNEL_REPLAY_READINESS_MARKERS = {
    "channel replay adapter readiness",
    "read-only channel replay adapter",
    "Feishu V1",
    "`/replay <trace_id>`",
    "explicit command only",
    "must call TaskReplayService",
    "must not assemble timeline",
    "must not query TaskEventService",
    "must not connect to stream queues",
    "must not reconstruct live SSE listener queues",
    "must not implement stream runtime replay",
    "must not implement observability UI",
    "must not enable CPE or AgentShield enforcement",
    "must not inspect customer content",
    "adapter DTO must be derived from the TaskReplayService DTO",
    "concise text summary",
    "bounded event count",
    "no natural-language 'last task' resolution",
    "no pagination in V1",
    "no Feishu card UI in V1",
    "no API replay endpoint",
    "Feishu `/replay <trace_id>` V1 is implemented as a separate small package",
}


def _readiness_text() -> str:
    assert READINESS_DOC.exists(), (
        "docs/observability/channel-replay-adapter-readiness.md is required"
    )
    return READINESS_DOC.read_text(encoding="utf-8")


def test_channel_replay_adapter_readiness_document_exists_and_defers_implementation():
    text = _readiness_text()

    assert "channel replay adapter readiness" in text
    assert "Feishu `/replay <trace_id>` V1 is implemented as a separate small package" in text


def test_channel_replay_adapter_readiness_names_required_boundaries():
    text = _readiness_text()
    missing = sorted(
        marker
        for marker in REQUIRED_CHANNEL_REPLAY_READINESS_MARKERS
        if marker not in text
    )

    assert missing == []


def test_final_closeout_points_to_channel_replay_adapter_readiness():
    text = FINAL_CLOSEOUT_DOC.read_text(encoding="utf-8")

    assert "docs/observability/channel-replay-adapter-readiness.md" in text


def test_task_event_closeout_points_to_channel_replay_adapter_readiness():
    text = TASK_EVENT_CLOSEOUT_DOC.read_text(encoding="utf-8")

    assert "docs/observability/channel-replay-adapter-readiness.md" in text
