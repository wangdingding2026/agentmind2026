# Phase 3 Connector Discovery Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move connector marketplace read-side DTO assembly out of the panel and into a service-layer boundary.

**Architecture:** `ConnectorDiscoveryService` owns the control-plane view of available connector templates. The lower-level `agents.discovery` module remains the source of known agent profiles; panel only calls the service and returns its result. This package does not change auto-discovery execution, ProtocolGateway connectors, or Feishu/ChannelHub runtime lifecycle.

**Tech Stack:** FastAPI panel router, service-layer Python class, pytest, existing `AgentProfile` and `KNOWN_AGENTS`.

---

## Scope

Target in this package:

- Add `src/agentmind/services/connector_discovery_service.py`.
- Add `tests/test_connector_discovery_service.py`.
- Move `GET /panel/api/connectors` DTO assembly from panel to service.
- Update panel boundary audit so `list_connectors` becomes service-backed.

Transition boundaries preserved:

- `feishu_connect`
- `feishu_disconnect`
- `feishu_status`
- `active_sessions`
- `attach_to_task`
- `panel_task_stream`

Out of scope:

- Do not run CLI auto-discovery.
- Do not change `agents.discovery.KNOWN_AGENTS`.
- Do not change ProtocolGateway connector invocation.
- Do not create ChannelHub.

## Files

- Create: `src/agentmind/services/connector_discovery_service.py`
  - Provides `list_connectors()` and maps profiles to panel connector DTOs.
- Create: `tests/test_connector_discovery_service.py`
  - Tests DTO mapping and injectable profile source.
- Modify: `src/agentmind/panel/server.py`
  - Imports and constructs `ConnectorDiscoveryService`.
  - Delegates `list_connectors` to the service.
- Modify: `tests/test_panel_api.py`
  - Adds delegation test for `GET /panel/api/connectors`.
- Modify: `tests/test_panel_control_plane_boundary.py`
  - Moves `list_connectors` from transition to service-backed.
- Modify: `docs/phase3/panel-control-plane-boundary.md`
  - Updates target/transition lists and next migration direction.

## Tasks

### Task 1: RED Service Tests

- [ ] **Step 1: Write failing service tests**

Add tests for:

- `list_connectors()` returns `{"connectors": [...]}`.
- Each DTO contains `id`, `name`, `type`, `tags`, `description`, and `timeout`.
- `description` preserves the existing `自动发现：<detect_commands>` display format.
- The service accepts an injected profile source so tests do not depend on global `KNOWN_AGENTS`.

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_connector_discovery_service.py -q
```

Expected: FAIL because `ConnectorDiscoveryService` does not exist.

### Task 2: GREEN Service

- [ ] **Step 1: Implement `ConnectorDiscoveryService`**

Use dependency injection:

- optional `profiles`
- default profile source imports `agentmind.agents.discovery.KNOWN_AGENTS`

- [ ] **Step 2: Run service GREEN**

```bash
pytest tests/test_connector_discovery_service.py -q
```

Expected: PASS.

### Task 3: RED Panel Delegation

- [ ] **Step 1: Add panel delegation test**

Monkeypatch `agentmind.panel.server.ConnectorDiscoveryService`, call:

```text
GET /panel/api/connectors
```

Assert the response is returned from `service.list_connectors()`.

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_connectors_endpoint_uses_connector_discovery_service -q
```

Expected: FAIL because panel still imports `KNOWN_AGENTS` directly.

### Task 4: GREEN Panel Migration

- [ ] **Step 1: Migrate panel handler**

Add `_connector_discovery_service()` helper and delegate `list_connectors`.

- [ ] **Step 2: Update boundary audit**

Move `list_connectors` from transition to service-backed and remove connector discovery from transition notes.

- [ ] **Step 3: Run focused GREEN**

```bash
pytest tests/test_connector_discovery_service.py tests/test_panel_api.py::TestPanelConfigServiceUsage::test_connectors_endpoint_uses_connector_discovery_service tests/test_panel_control_plane_boundary.py -q
```

Expected: PASS.

### Task 5: Verification

- [ ] **Step 1: Run panel regression**

```bash
pytest tests/test_panel_api.py -q
```

- [ ] **Step 2: Run connector/service regression**

```bash
pytest tests/test_connector_discovery_service.py tests/test_protocol_gateway.py -q
```

- [ ] **Step 3: Run architecture regression**

```bash
pytest tests/test_phase2_architecture_audit.py tests/test_panel_control_plane_boundary.py -q
```

- [ ] **Step 4: Run router/panel regression**

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

- [ ] **Step 5: Run full regression**

```bash
pytest -q
```

### Task 6: Commit

- [ ] **Step 1: Check diff hygiene**

```bash
git diff --check
git status --short
```

- [ ] **Step 2: Review and commit**

```bash
git add docs/superpowers/plans/2026-05-27-phase-3-connector-discovery-service.md docs/phase3/panel-control-plane-boundary.md src/agentmind/services/connector_discovery_service.py src/agentmind/panel/server.py tests/test_connector_discovery_service.py tests/test_panel_api.py tests/test_panel_control_plane_boundary.py
git commit -m "refactor: route connector discovery through service"
```

## Self-Review

- Spec coverage: Covers connector marketplace read-side only.
- Placeholder scan: No TODO/TBD/fill-in markers.
- Architecture fit: Panel remains an adapter, service owns DTO assembly, discovery profile definitions stay below the service boundary.
