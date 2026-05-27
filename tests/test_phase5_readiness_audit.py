from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE5_DOC = PROJECT_ROOT / "docs" / "phase5" / "phase-5-readiness.md"
PHASE4_DOC = PROJECT_ROOT / "docs" / "phase4" / "phase-4-closure-status.md"


REQUIRED_PHASE5_MARKERS = {
    "Phase 5 readiness",
    "security governance readiness",
    "docs/phase4/phase-4-closure-status.md",
    "Phase 4 is closed",
    "service/rule/channel boundaries",
    "services do the work",
    "rule/core layers own rules",
    "panel/API/channel remain adapters",
    "CPE",
    "AgentShield",
    "do not implement CPE",
    "do not implement AgentShield",
    "persistent task-event replay",
    "observability/task-event",
    "feishu.route_callback",
    "bounded migration fallback",
    "delete criteria",
    "ChannelMessage",
}


def _phase5_text() -> str:
    assert PHASE5_DOC.exists(), "docs/phase5/phase-5-readiness.md is required"
    return PHASE5_DOC.read_text(encoding="utf-8")


def test_phase5_readiness_document_exists_and_names_phase4_source():
    text = _phase5_text()

    assert "Phase 5 readiness" in text
    assert "docs/phase4/phase-4-closure-status.md" in text
    assert "Phase 4 is closed" in text


def test_phase5_readiness_document_names_required_boundaries_and_non_goals():
    text = _phase5_text()
    missing = sorted(marker for marker in REQUIRED_PHASE5_MARKERS if marker not in text)

    assert missing == []


def test_phase5_readiness_document_orders_work_before_security_implementation():
    text = _phase5_text()

    readiness = text.index("Phase 5 readiness")
    cpe_start = text.index("CPE start criteria")
    agent_shield_start = text.index("AgentShield start criteria")

    assert readiness < cpe_start < agent_shield_start
    assert "CPE implementation package" not in text
    assert "AgentShield implementation package" not in text


def test_phase4_closure_points_to_phase5_readiness_document():
    text = PHASE4_DOC.read_text(encoding="utf-8")

    assert "docs/phase5/phase-5-readiness.md" in text
    assert "Start Phase 5 readiness" in text
