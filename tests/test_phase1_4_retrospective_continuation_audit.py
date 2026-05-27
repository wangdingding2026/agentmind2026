from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTINUATION_DOC = (
    PROJECT_ROOT
    / "docs"
    / "phase4"
    / "phase-1-4-retrospective-continuation.md"
)


REQUIRED_MARKERS = {
    "Phase 1-4 retrospective",
    "continue architecture refactor and optimization",
    "docs/phase4/phase-4-closure-status.md",
    "Phase 5 readiness",
    "Phase 6 readiness",
    "service/rule/channel boundaries",
    "panel/API/channel remain adapters",
    "services do the work",
    "rule/core layers own rules",
    "compatibility layer",
    "feishu.route_callback",
    "delete criteria",
    "persistent task-event replay",
    "observability/task-event",
    "do not implement CPE",
    "do not implement AgentShield",
    "do not start EvolutionEngine",
    "do not start TemplateMarket",
    "TDD",
    "RED",
    "GREEN",
    "focused tests",
    "router/panel regression",
    "full pytest",
}


def _doc_text() -> str:
    assert CONTINUATION_DOC.exists(), (
        "docs/phase4/phase-1-4-retrospective-continuation.md is required "
        "before running the Phase 1-4 retrospective"
    )
    return CONTINUATION_DOC.read_text(encoding="utf-8")


def test_phase1_4_retrospective_continuation_document_exists():
    text = _doc_text()

    assert "Phase 1-4 retrospective" in text
    assert "continue architecture refactor and optimization" in text


def test_phase1_4_retrospective_continuation_document_names_required_markers():
    text = _doc_text()
    missing = sorted(marker for marker in REQUIRED_MARKERS if marker not in text)

    assert missing == []


def test_phase1_4_retrospective_continuation_document_orders_next_work():
    text = _doc_text()

    retrospective = text.index("Phase 1-4 retrospective")
    phase5 = text.index("Phase 5 readiness")
    phase6 = text.index("Phase 6 readiness")

    assert retrospective < phase5 < phase6
    assert "CPE/AgentShield implementation" not in text
    assert "EvolutionEngine implementation" not in text
