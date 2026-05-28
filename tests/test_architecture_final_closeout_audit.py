from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FINAL_CLOSEOUT_DOC = PROJECT_ROOT / "docs" / "architecture" / "final-closeout-status.md"
PHASE3_CLOSURE_DOC = PROJECT_ROOT / "docs" / "phase3" / "phase-3-closure-status.md"
PHASE4_CLOSURE_DOC = PROJECT_ROOT / "docs" / "phase4" / "phase-4-closure-status.md"
PHASE5_CLOSURE_DOC = PROJECT_ROOT / "docs" / "phase5" / "phase-5-closure-status.md"
TASK_EVENT_CLOSEOUT_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "task-event-closeout-status.md"
)
FEISHU_DELETION_DOC = (
    PROJECT_ROOT / "docs" / "phase4" / "feishu-route-callback-deletion-readiness.md"
)


REQUIRED_FINAL_CLOSEOUT_MARKERS = {
    "AgentMind architecture refactor route is closed",
    "Phase 1 service-layer foundation is complete",
    "Phase 2 memory and trace convergence is complete",
    "Phase 3 platform-core and control-plane service boundaries are closed",
    "Phase 4 control-panel runtime and channel boundary work is closed",
    "Phase 5 permissive governance architecture baseline is closed",
    "observability/task-event route is closed",
    "Feishu `route_callback` fallback has been removed",
    "services do the work",
    "rule/core layers own rules and decisions",
    "panel/API/channel remain adapters",
    "TaskEventService owns stored task timeline events",
    "TaskTimelineService owns read-side timeline DTO assembly",
    "TaskReplayService owns the service-level replay DTO boundary",
    "panel `task_replay` handler calls TaskReplayService",
    "stream_snapshot remains in-process backlog only",
    "live SSE listener queues are not persisted or restored",
    "CPE remains permissive",
    "AgentShield remains permissive",
    "content_inspection=false",
    "behavior_inspection=false",
    "no customer-content inspection",
    "no CPE or AgentShield enforcement",
    "no self-evolution work",
    "no TemplateMarket work",
    "no API replay endpoint",
    "no advanced channel replay UX beyond Feishu `/replay <trace_id>` V1",
    "no advanced observability UI beyond Panel Observability UI V1",
    "no stream runtime replay",
    "future packages require separate implementation plans",
}


def _final_closeout_text() -> str:
    assert FINAL_CLOSEOUT_DOC.exists(), (
        "docs/architecture/final-closeout-status.md is required"
    )
    return FINAL_CLOSEOUT_DOC.read_text(encoding="utf-8")


def test_architecture_final_closeout_document_exists_and_declares_closed():
    text = _final_closeout_text()

    assert "AgentMind architecture refactor route is closed" in text
    assert "Final Closeout Decision" in text


def test_architecture_final_closeout_document_names_required_boundaries():
    text = _final_closeout_text()
    missing = sorted(
        marker for marker in REQUIRED_FINAL_CLOSEOUT_MARKERS if marker not in text
    )

    assert missing == []


def test_final_closeout_links_to_required_closure_sources():
    text = _final_closeout_text()

    assert "docs/phase3/phase-3-closure-status.md" in text
    assert "docs/phase4/phase-4-closure-status.md" in text
    assert "docs/phase5/phase-5-closure-status.md" in text
    assert "docs/observability/task-event-closeout-status.md" in text
    assert "docs/phase4/feishu-route-callback-deletion-readiness.md" in text


def test_recent_closure_docs_point_to_final_closeout():
    required_link = "docs/architecture/final-closeout-status.md"

    for path in (
        PHASE5_CLOSURE_DOC,
        TASK_EVENT_CLOSEOUT_DOC,
        FEISHU_DELETION_DOC,
    ):
        text = path.read_text(encoding="utf-8")
        assert required_link in text


def test_historical_closure_docs_remain_available_as_sources():
    for path in (
        PHASE3_CLOSURE_DOC,
        PHASE4_CLOSURE_DOC,
        PHASE5_CLOSURE_DOC,
        TASK_EVENT_CLOSEOUT_DOC,
        FEISHU_DELETION_DOC,
    ):
        assert path.exists()
