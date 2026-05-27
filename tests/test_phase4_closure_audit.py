from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE4_DOC = PROJECT_ROOT / "docs" / "phase4" / "phase-4-closure-status.md"
PHASE3_DOC = PROJECT_ROOT / "docs" / "phase3" / "phase-3-closure-status.md"
PANEL_BOUNDARY_DOC = PROJECT_ROOT / "docs" / "phase3" / "panel-control-plane-boundary.md"


REQUIRED_PHASE4_MARKERS = {
    "Phase 4 is closed",
    "ChannelHub",
    "channel lifecycle",
    "channel status",
    "startup Feishu auto-start",
    "ChannelMessage",
    "Feishu inbound",
    "discussion stop-word",
    "feishu.route_callback",
    "migration fallback",
    "delete after",
    "SessionRuntimeService",
    "active_sessions",
    "attach_to_task",
    "panel_task_stream",
    "stream_snapshot",
    "active discussion state",
    "attach bindings",
    "startup recovery",
    "live stream listener queues remain volatile",
    "persistent task-event replay",
    "observability/task-event",
    "Phase 5 readiness",
}


def _phase4_text() -> str:
    assert PHASE4_DOC.exists(), "docs/phase4/phase-4-closure-status.md is required"
    return PHASE4_DOC.read_text(encoding="utf-8")


def test_phase4_closure_document_exists_and_declares_closed():
    text = _phase4_text()

    assert "Phase 4 is closed" in text
    assert "ChannelHub" in text
    assert "SessionRuntimeService" in text


def test_phase4_closure_document_names_required_boundaries():
    text = _phase4_text()
    missing = sorted(marker for marker in REQUIRED_PHASE4_MARKERS if marker not in text)

    assert missing == []


def test_phase3_docs_reference_phase4_closure_and_phase5_readiness():
    docs = "\n".join([
        PHASE3_DOC.read_text(encoding="utf-8"),
        PANEL_BOUNDARY_DOC.read_text(encoding="utf-8"),
    ])

    assert "docs/phase4/phase-4-closure-status.md" in docs
    assert "Phase 5 readiness" in docs
    assert "Phase 4 closeout/readiness audit" not in docs
