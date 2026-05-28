from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_CLOSEOUT_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "observability-product-closeout-status.md"
)
TASK_EVENT_CLOSEOUT_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-closeout-status.md"
)
CHANNEL_READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "channel-replay-adapter-readiness.md"
)
UI_READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "observability-ui-readiness.md"
)
FINAL_CLOSEOUT_DOC = PROJECT_ROOT / "docs" / "architecture" / "final-closeout-status.md"


REQUIRED_PRODUCT_CLOSEOUT_MARKERS = {
    "observability productization route is closed",
    "TaskReplayService owns the service-level replay DTO boundary",
    "panel `task_replay` handler calls TaskReplayService",
    "Feishu channel replay V1 is implemented",
    "ChannelReplayService",
    "Panel Observability UI V1 is implemented",
    "`/panel/api/tasks/{trace_id}/replay`",
    "Replay uses persisted task timeline events",
    "partial_output events may be displayed",
    "panel/API/channel remain adapters",
    "stream_snapshot remains in-process backlog only",
    "live SSE listener queues are not persisted or restored",
    "no API replay endpoint",
    "no advanced channel replay UX beyond Feishu `/replay <trace_id>` V1",
    "no advanced observability UI beyond Panel Observability UI V1",
    "no stream runtime replay",
    "no CPE or AgentShield enforcement",
    "no customer-content inspection",
}


def _product_closeout_text() -> str:
    assert PRODUCT_CLOSEOUT_DOC.exists(), (
        "docs/observability/observability-product-closeout-status.md is required"
    )
    return PRODUCT_CLOSEOUT_DOC.read_text(encoding="utf-8")


def test_observability_product_closeout_document_exists_and_declares_closed():
    text = _product_closeout_text()

    assert "observability productization route is closed" in text
    assert "Product Closeout Decision" in text


def test_observability_product_closeout_names_required_boundaries():
    text = _product_closeout_text()
    missing = sorted(
        marker for marker in REQUIRED_PRODUCT_CLOSEOUT_MARKERS if marker not in text
    )

    assert missing == []


def test_related_observability_docs_point_to_product_closeout():
    required_link = "docs/observability/observability-product-closeout-status.md"

    for path in (
        TASK_EVENT_CLOSEOUT_DOC,
        CHANNEL_READINESS_DOC,
        UI_READINESS_DOC,
        FINAL_CLOSEOUT_DOC,
    ):
        text = path.read_text(encoding="utf-8")
        assert required_link in text
