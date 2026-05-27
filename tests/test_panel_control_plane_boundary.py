import ast
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PANEL_SERVER = PROJECT_ROOT / "src" / "agentmind" / "panel" / "server.py"
BOUNDARY_DOC = PROJECT_ROOT / "docs" / "phase3" / "panel-control-plane-boundary.md"


SERVICE_BACKED_HANDLERS = {
    "list_tasks",
    "task_stats",
    "recent_errors",
    "task_detail",
    "task_explanation",
    "routing_trace",
    "audit_events",
    "routing_explanation",
    "routing_strategies",
    "control_overview",
    "list_agents",
    "list_agent_capabilities",
    "add_agent",
    "restart_agent",
    "update_agent_tags",
    "toggle_agent",
    "service_status",
    "memory_search",
    "memory_stats",
    "memory_delete",
    "memory_cleanup",
    "service_metrics",
    "feishu_save_config",
    "list_rules",
    "save_rule",
    "delete_rule",
    "save_settings",
}

REQUIRED_TRANSITION_HANDLERS = {
    "feishu_get_config",
    "feishu_connect",
    "feishu_disconnect",
    "feishu_status",
    "active_sessions",
    "get_settings",
    "embedding_status",
    "attach_to_task",
    "panel_task_stream",
    "list_connectors",
}

FORBIDDEN_SERVICE_BACKED_PATTERNS = {
    "request.app.state.agent_registry.executors": "panel must not traverse executor registry",
    "CLIExecutor(": "panel must not construct executors",
    "ConfigService(CONFIG_DIR).update_settings_sections": "settings writes belong behind services",
    "ConfigService(CONFIG_DIR).write_settings": "settings writes belong behind services",
    ".read_routes(": "rule file reads belong behind rule/config services",
    ".write_routes(": "rule file writes belong behind rule/config services",
    "rule_engine.reload": "rule reload belongs behind RuleControlService",
    "_query_tasks_sync": "task storage queries belong behind TaskService",
    "from agentmind.storage.db import record_task": "task writes belong behind TaskService",
    "from agentmind.storage.db import query_tasks": "task reads belong behind TaskService",
    "FeishuAdapter(": "channel lifecycle belongs behind the future ChannelHub boundary",
    "route_stream(": "routing execution belongs behind routing/channel services",
    "session_registry": "session runtime state belongs behind a service boundary",
    "attach_registry": "attach runtime state belongs behind a service boundary",
    "has_local_embedding": "embedding runtime checks belong behind a service boundary",
    "KNOWN_AGENTS": "connector discovery belongs behind a service boundary",
}

DIRECT_TRANSITION_PATTERNS = {
    "ConfigService(CONFIG_DIR).read_settings",
    "ConfigService(CONFIG_DIR).update_settings_sections",
    "ConfigService(CONFIG_DIR).write_settings",
    "request.app.state.settings",
    "request.app.state.feishu_adapter",
    "FeishuAdapter(",
    "route_stream(",
    "session_registry",
    "_query_tasks_sync",
    "attach_registry",
    "has_local_embedding",
    "KNOWN_AGENTS",
}


def _route_handler_sources() -> dict[str, str]:
    source = PANEL_SERVER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    create_router = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "create_panel_router"
    )
    handlers = {}
    for node in create_router.body:
        if isinstance(node, ast.AsyncFunctionDef):
            handlers[node.name] = ast.get_source_segment(source, node) or ""
    return handlers


def _documented_transition_handlers() -> set[str]:
    assert BOUNDARY_DOC.exists(), (
        "Phase 3 panel boundary inventory is required at "
        "docs/phase3/panel-control-plane-boundary.md"
    )
    text = BOUNDARY_DOC.read_text(encoding="utf-8")
    return set(re.findall(r"`([a-zA-Z_][a-zA-Z0-9_]*)`", text))


def test_panel_boundary_inventory_documents_transition_handlers():
    documented = _documented_transition_handlers()
    missing = REQUIRED_TRANSITION_HANDLERS - documented
    assert missing == set()


def test_service_backed_panel_handlers_do_not_reintroduce_direct_business_logic():
    handlers = _route_handler_sources()
    missing_handlers = SERVICE_BACKED_HANDLERS - set(handlers)
    assert missing_handlers == set()

    offenders = {}
    for handler_name in sorted(SERVICE_BACKED_HANDLERS):
        source = handlers[handler_name]
        violations = [
            f"{pattern}: {reason}"
            for pattern, reason in FORBIDDEN_SERVICE_BACKED_PATTERNS.items()
            if pattern in source
        ]
        if violations:
            offenders[handler_name] = violations

    assert offenders == {}


def test_remaining_direct_panel_runtime_logic_is_documented_as_transition_only():
    documented = _documented_transition_handlers()
    handlers = _route_handler_sources()

    offenders = {}
    for handler_name, source in sorted(handlers.items()):
        direct_patterns = sorted(
            pattern for pattern in DIRECT_TRANSITION_PATTERNS if pattern in source
        )
        if direct_patterns and handler_name not in documented:
            offenders[handler_name] = direct_patterns

    assert offenders == {}
