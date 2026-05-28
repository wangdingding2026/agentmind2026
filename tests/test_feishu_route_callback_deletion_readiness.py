from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
READINESS_DOC = PROJECT_ROOT / "docs" / "phase4" / "feishu-route-callback-deletion-readiness.md"
PHASE4_CLOSURE_DOC = PROJECT_ROOT / "docs" / "phase4" / "phase-4-closure-status.md"
TASK_EVENT_CLOSEOUT_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-closeout-status.md"
)


REQUIRED_DELETION_READINESS_MARKERS = {
    "Feishu route_callback deletion readiness",
    "`feishu.route_callback` fallback has been removed",
    "deleted in this package",
    "ChannelHub owns Feishu channel lifecycle",
    "ChannelHub no longer constructs `route_callback`",
    "FeishuAdapter no longer executes `route_callback`",
    "standard inbound path uses `ChannelMessage`",
    "standard `message_callback` path remains supported",
    "no new Feishu business behavior",
    "no route_stream fallback expansion",
    "no channel replay adapter",
    "no observability UI",
    "no CPE or AgentShield enforcement",
    "no customer-content inspection",
}


def _readiness_text() -> str:
    assert READINESS_DOC.exists(), (
        "docs/phase4/feishu-route-callback-deletion-readiness.md is required"
    )
    return READINESS_DOC.read_text(encoding="utf-8")


def test_feishu_route_callback_deletion_readiness_document_exists_and_defers_deletion():
    text = _readiness_text()

    assert "Feishu route_callback deletion readiness" in text
    assert "`feishu.route_callback` fallback has been removed" in text
    assert "deleted in this package" in text


def test_feishu_route_callback_deletion_readiness_names_required_boundaries():
    text = _readiness_text()
    missing = sorted(
        marker for marker in REQUIRED_DELETION_READINESS_MARKERS if marker not in text
    )

    assert missing == []


def test_phase4_closure_points_to_feishu_route_callback_deletion_readiness():
    text = PHASE4_CLOSURE_DOC.read_text(encoding="utf-8")

    assert "docs/phase4/feishu-route-callback-deletion-readiness.md" in text


def test_task_event_closeout_points_to_feishu_route_callback_deletion_readiness():
    text = TASK_EVENT_CLOSEOUT_DOC.read_text(encoding="utf-8")

    assert "docs/phase4/feishu-route-callback-deletion-readiness.md" in text
