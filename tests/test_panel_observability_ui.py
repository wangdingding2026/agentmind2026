from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PANEL_HTML = PROJECT_ROOT / "src" / "agentmind" / "panel" / "static" / "index.html"
PANEL_JS = PROJECT_ROOT / "src" / "agentmind" / "panel" / "static" / "dashboard.js"
READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "observability-ui-readiness.md"
)


REQUIRED_UI_MARKERS = {
    'id="task-replay-panel"',
    'id="task-replay-title"',
    'id="task-replay-content"',
    "loadTaskReplay(",
    "renderTaskReplay(",
    "formatReplayEvent(",
    "btn-task-replay",
    '"/tasks/" + encodeURIComponent(traceId) + "/replay?limit=50"',
    "任务回放",
    "未找到持久化任务事件",
    "partial_output",
}


FORBIDDEN_UI_MARKERS = {
    "TaskEventService",
    "TaskTimelineService",
    "stream_snapshot",
    "/panel/api/task-events",
    "/replay/stream",
}


def _panel_html() -> str:
    assert PANEL_HTML.exists(), "panel static index.html is required"
    return PANEL_HTML.read_text(encoding="utf-8")


def _panel_static_text() -> str:
    html = _panel_html()
    js = PANEL_JS.read_text(encoding="utf-8") if PANEL_JS.exists() else ""
    return html + "\n" + js


def test_panel_observability_ui_static_page_contains_replay_view():
    html = _panel_static_text()
    missing = sorted(marker for marker in REQUIRED_UI_MARKERS if marker not in html)

    assert missing == []


def test_panel_observability_ui_does_not_bypass_replay_adapter_boundary():
    html = _panel_static_text()
    forbidden = sorted(marker for marker in FORBIDDEN_UI_MARKERS if marker in html)

    assert forbidden == []


def test_observability_ui_readiness_records_panel_v1_implementation():
    text = READINESS_DOC.read_text(encoding="utf-8")

    assert "Panel Observability UI V1 is implemented" in text
    assert "`/panel/api/tasks/{trace_id}/replay`" in text
