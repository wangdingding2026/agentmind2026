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


def test_panel_commander_dashboard_deduplicates_command_health_overview():
    html = _read(PANEL_HTML)
    js = _read(PANEL_JS)

    assert "系统状态总览" in html
    assert 'id="command-status-overview"' in html
    assert "系统健康" not in html
    assert 'id="command-health-list"' not in html
    assert "function renderCommandStatusOverview" in js
    assert "renderCommandMetrics" not in js
    assert "renderCommandHealth" not in js


def test_panel_commander_dashboard_localizes_user_visible_status_codes():
    html = _read(PANEL_HTML)
    js = _read(PANEL_JS)

    for text in [
        "指挥舱总览",
        "任务工作台",
        "Agent 工作台",
        "路由工作台",
        "审计工作台",
        "记忆工作台",
        "编排工作台",
        "系统配置",
        "任务详情",
    ]:
        assert text in html

    for text in [
        "function formatSystemStatus",
        "function formatStage",
        "function formatReplayStatus",
        "function formatReplaySource",
        "function formatEventType",
        "function formatAuditModule",
        "function formatAuditAction",
        "部分异常",
        "配置",
        "更新",
        "可回放",
        "任务事件",
        "片段输出",
    ]:
        assert text in js

    for text in [
        "Command Center",
        "Task Workbench",
        "Agent Workbench",
        "Routing Workbench",
        "Audit Workbench",
        "Memory Workbench",
        "Orchestration Workbench",
        "Settings",
        "Task Detail",
    ]:
        assert text not in html


def test_panel_audit_workbench_shows_specific_object_column():
    html = _read(PANEL_HTML)
    js = _read(PANEL_JS)

    assert "<th>对象</th>" in html
    assert "function formatAuditObject" in js
    assert "Embedding 配置" in js
    assert "系统设置" not in js


def test_panel_settings_page_uses_horizontal_form_rows():
    html = _read(PANEL_HTML)
    css = _read(PANEL_CSS)

    assert 'class="settings-form"' in html
    assert html.count('class="settings-row"') >= 14
    assert ".settings-grid .settings-row" in css
    assert "grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));" in css
    assert ".settings-actions" in css
    assert ".settings-grid label { padding:" not in css
    assert ".settings-grid label {\n  display: flex;\n  flex-direction: column;" not in css


def test_panel_settings_page_lays_out_fields_across_each_panel():
    html = _read(PANEL_HTML)
    css = _read(PANEL_CSS)

    assert html.count('class="settings-section"') == 5
    assert html.count('class="settings-section-title"') == 5
    assert 'id="settings-feishu-section"' in html
    assert '<section class="settings-section" id="settings-feishu-section">' in html
    assert '<div class="settings-section-title">飞书通道</div>' in html
    settings_html = html[html.index('id="page-settings"'):]
    assert 'class="panel-head"><h2>飞书通道</h2>' not in settings_html
    assert ".settings-grid {\n  display: flex;" in css
    assert ".settings-section" in css
    assert ".settings-section-title" in css
    assert ".settings-form {\n  display: grid;" in css
    assert "grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));" in css
    assert ".settings-grid .settings-row {\n  display: flex;" in css
    settings_actions = re.search(r"\.settings-actions \{(?P<body>.*?)\n\}", css, re.S)
    assert settings_actions is not None
    assert "padding-left: 0;" in settings_actions.group("body")


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


def test_panel_commander_dashboard_all_actions_have_handlers():
    html = _read(PANEL_HTML)
    js = _read(PANEL_JS)

    html_actions = set(re.findall(r'data-action="([^"]+)"', html))
    dynamic_actions = {
        "open-task-detail",
        "test-agent",
        "restart-agent",
        "edit-agent-tags",
        "toggle-agent",
        "delete-route-rule",
        "delete-memory",
        "delete-orchestration",
    }
    missing = sorted(
        action
        for action in html_actions | dynamic_actions
        if f"'{action}':" not in js
    )

    assert missing == []
