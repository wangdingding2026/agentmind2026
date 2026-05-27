import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVICES_DIR = PROJECT_ROOT / "src" / "agentmind" / "services"
PHASE3_DOC = PROJECT_ROOT / "docs" / "phase3" / "phase-3-closure-status.md"
PANEL_BOUNDARY_DOC = PROJECT_ROOT / "docs" / "phase3" / "panel-control-plane-boundary.md"


REQUIRED_SERVICE_FILES = {
    "strategy_manager.py",
    "protocol_gateway.py",
    "capability_registry.py",
    "orchestration_service.py",
    "audit_service.py",
    "control_plane_overview_service.py",
    "agent_control_service.py",
    "rule_control_service.py",
    "settings_control_service.py",
    "settings_status_service.py",
    "connector_discovery_service.py",
    "session_runtime_service.py",
}

REQUIRED_DOCUMENT_MARKERS = {
    "StrategyManager",
    "ProtocolGateway",
    "AgentCapabilityRegistry",
    "OrchestrationEngine",
    "AuditService",
    "ControlPlaneOverviewService",
    "AgentControlService",
    "RuleControlService",
    "SettingsControlService",
    "SettingsStatusService",
    "ConnectorDiscoveryService",
    "SessionRuntimeService",
    "ChannelHub",
    "feishu_connect",
    "feishu_disconnect",
    "feishu_status",
}

EXPECTED_PANEL_TRANSITIONS = set()


def test_phase3_closure_status_document_exists_and_names_required_boundaries():
    assert PHASE3_DOC.exists(), "docs/phase3/phase-3-closure-status.md is required"

    text = PHASE3_DOC.read_text(encoding="utf-8")
    missing = sorted(marker for marker in REQUIRED_DOCUMENT_MARKERS if marker not in text)
    assert missing == []


def test_phase3_required_service_files_exist():
    missing = sorted(
        service_file
        for service_file in REQUIRED_SERVICE_FILES
        if not (SERVICES_DIR / service_file).exists()
    )
    assert missing == []


def test_phase3_panel_transition_scope_is_limited_to_feishu_lifecycle():
    text = PANEL_BOUNDARY_DOC.read_text(encoding="utf-8")
    full_transition_section = text.split("## Transition Handlers", maxsplit=1)[1].split(
        "## Next Migration Direction",
        maxsplit=1,
    )[0]
    transition_list = full_transition_section.split(
        "Current boundary notes:",
        maxsplit=1,
    )[0]
    documented = {
        match
        for line in transition_list.splitlines()
        for match in re.findall(r"^- `([a-zA-Z_][a-zA-Z0-9_]*)`", line)
    }

    assert documented == EXPECTED_PANEL_TRANSITIONS
    assert "Phase 4 `ChannelHub`" in full_transition_section
