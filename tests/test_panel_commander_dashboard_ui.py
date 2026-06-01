from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PANEL_STATIC = PROJECT_ROOT / "src" / "agentmind" / "panel" / "static"
PANEL_HTML = PANEL_STATIC / "index.html"
PANEL_CSS = PANEL_STATIC / "dashboard.css"
PANEL_JS = PANEL_STATIC / "dashboard.js"


REQUIRED_PAGES = {
    "command": "指挥舱",
    "tasks": "任务台",
    "agents": "Agent 台",
    "routing": "路由台",
    "audit": "审计台",
    "memory": "记忆台",
    "orchestrator": "编排台",
    "settings": "配置",
}


def _read(path: Path) -> str:
    assert path.exists(), f"{path.name} is required"
    return path.read_text(encoding="utf-8")


def test_panel_commander_dashboard_static_assets_are_split():
    html = _read(PANEL_HTML)

    assert 'href="dashboard.css"' in html
    assert 'src="dashboard.js"' in html
    assert "<style>" not in html
    assert "<script>" not in html


def test_panel_commander_dashboard_declares_v1_workbenches():
    html = _read(PANEL_HTML)

    for page_id, label in REQUIRED_PAGES.items():
        assert f'data-page="{page_id}"' in html
        assert f'id="page-{page_id}"' in html
        assert label in html


def test_panel_commander_dashboard_has_task_detail_drawer():
    html = _read(PANEL_HTML)

    required = {
        'id="task-replay-panel"',
        'data-detail-drawer',
        'id="task-replay-title"',
        'id="task-detail-summary"',
        'id="task-detail-routing"',
        'id="task-replay-content"',
        'id="task-detail-audit"',
    }
    missing = sorted(marker for marker in required if marker not in html)

    assert missing == []


def test_panel_commander_dashboard_js_uses_existing_service_adapters():
    js = _read(PANEL_JS)

    required = {
        "/control/overview",
        "/tasks?limit=50",
        '"/tasks/" + encodeURIComponent(traceId) + "/explanation"',
        '"/tasks/" + encodeURIComponent(traceId) + "/replay?limit=50"',
        "/routing/strategies",
        "/audit/events",
        "/memory/search",
        "/settings",
        "/feishu/status",
        "/embedding/status",
        "/agents/' + encodeURIComponent(agentId) + '/tags",
    }
    missing = sorted(marker for marker in required if marker not in js)

    assert missing == []


def test_panel_commander_dashboard_preserves_agent_tag_editing():
    js = _read(PANEL_JS)

    assert "'edit-agent-tags': () => editAgentTags(id)" in js
    assert "async function editAgentTags(agentId)" in js
    assert "JSON.stringify({ tags })" in js


def test_panel_commander_dashboard_preserves_orchestrator_parent_callback():
    js = _read(PANEL_JS)

    assert "function loadOrchPlans()" in js
    assert "return loadOrchestrationPlans();" in js


def test_panel_commander_dashboard_empty_task_rows_match_table_columns():
    js = _read(PANEL_JS)

    assert '<tr><td colspan="7" class="empty">暂无任务</td></tr>' in js
    assert '<tr><td colspan="6" class="empty">暂无任务</td></tr>' not in js


def test_panel_commander_dashboard_falls_back_from_stale_saved_page():
    js = _read(PANEL_JS)

    assert "function normalizePage(page)" in js
    assert "return PAGE_LOADERS[page] ? page : 'command';" in js
    initial_page = re.search(
        r"currentPage:\s*normalizePage\(localStorage\.getItem\('agentmind_commander_page'\)\)",
        js,
    )
    assert initial_page is not None


def test_panel_commander_dashboard_setting_toggles_update_only_after_success():
    js = _read(PANEL_JS)

    for function_name, button_id in {
        "toggleSemantic": "btn-sr-toggle",
        "toggleEmbedding": "btn-emb-toggle",
        "toggleCoreLLM": "btn-core-llm-toggle",
    }.items():
        match = re.search(
            rf"async function {function_name}\(\) \{{(?P<body>.*?)\n\}}",
            js,
            re.S,
        )
        assert match is not None
        body = match.group("body")
        assert f"if (ok) setToggleBtn('{button_id}', enabled);" in body
        unconditional_updates = [
            line
            for line in body.splitlines()
            if f"setToggleBtn('{button_id}', enabled);" in line
            and "if (ok)" not in line
        ]
        assert unconditional_updates == []
