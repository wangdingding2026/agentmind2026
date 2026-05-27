from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE5_CLOSURE_DOC = PROJECT_ROOT / "docs" / "phase5" / "phase-5-closure-status.md"
PHASE5_READINESS_DOC = PROJECT_ROOT / "docs" / "phase5" / "phase-5-readiness.md"


REQUIRED_PHASE5_CLOSURE_MARKERS = {
    "Phase 5 is closed",
    "permissive governance architecture baseline",
    "CPE",
    "does not inspect customer message content",
    "content_inspection=false",
    "AgentShield",
    "does not inspect behavior payloads",
    "behavior_inspection=false",
    "RoutingService",
    "dry-run",
    "does not block, reroute, or require approval",
    "AuditService",
    "governance event shape",
    "future status mapping",
    "panel/API/channel remain adapters",
    "do not own governance rules",
    "feishu.route_callback",
    "bounded migration fallback",
    "persistent task-event replay",
    "observability/task-event",
    "Phase 6 readiness",
    "Phase 6 implementation has not started",
}


def _phase5_closure_text() -> str:
    assert PHASE5_CLOSURE_DOC.exists(), (
        "docs/phase5/phase-5-closure-status.md is required"
    )
    return PHASE5_CLOSURE_DOC.read_text(encoding="utf-8")


def test_phase5_closure_document_exists_and_declares_closed():
    text = _phase5_closure_text()

    assert "Phase 5 is closed" in text
    assert "permissive governance architecture baseline" in text


def test_phase5_closure_document_names_required_boundaries():
    text = _phase5_closure_text()
    missing = sorted(marker for marker in REQUIRED_PHASE5_CLOSURE_MARKERS if marker not in text)

    assert missing == []


def test_phase5_readiness_points_to_phase5_closure_and_phase6_readiness():
    text = PHASE5_READINESS_DOC.read_text(encoding="utf-8")

    assert "docs/phase5/phase-5-closure-status.md" in text
    assert "Phase 6 readiness" in text
