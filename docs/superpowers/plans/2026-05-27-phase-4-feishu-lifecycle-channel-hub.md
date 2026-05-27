# Phase 4 Feishu Lifecycle ChannelHub Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move panel Feishu connect/disconnect/status lifecycle operations behind the `ChannelHub` boundary while keeping existing endpoint response shapes.

**Architecture:** `ChannelHub` owns channel lifecycle work. Panel reads request JSON, calls `ChannelHub`, and returns the service result. Feishu adapter construction and route callback creation move out of panel into the hub. Startup auto-start and `FeishuAdapter` message-processing internals remain transition paths for later packages.

**Tech Stack:** FastAPI panel router, `ChannelHub`, existing `FeishuAdapter`, existing `ConfigService`, pytest.

---

## Scope

Target in this package:

- Extend `ChannelHub` with Feishu lifecycle methods:
  - `connect_feishu(app, app_id, app_secret)`
  - `disconnect_feishu(app)`
  - `feishu_status(app)`
- Move panel Feishu lifecycle code into `ChannelHub`.
- Keep existing endpoint shapes:
  - connect success: `{"ok": True, "connected": True}`
  - connect failure: `{"ok": False, "error": "..."}`
  - disconnect: `{"ok": True}`
  - status: `{"enabled": bool, "connected": bool}`
- Update panel boundary audit so `feishu_connect`, `feishu_disconnect`, and `feishu_status` are service-backed.

Transition boundaries preserved:

- `startup.py::_maybe_start_feishu`
- `FeishuAdapter` route callback and message loop internals

Out of scope:

- Do not migrate startup auto-start in this package.
- Do not remove `route_stream` from Feishu path yet.
- Do not add webhook/API channels.
- Do not change panel static UI.

## Files

- Modify: `src/agentmind/channels/hub.py`
  - Adds Feishu lifecycle methods and adapter factory injection.
- Modify: `src/agentmind/panel/server.py`
  - Adds `_channel_hub(request)` helper.
  - Delegates Feishu connect/disconnect/status to hub.
- Modify: `tests/test_channel_hub.py`
  - Adds Feishu lifecycle tests with fake adapter factory.
- Modify: `tests/test_panel_api.py`
  - Adds panel delegation tests for Feishu lifecycle endpoints.
- Modify: `tests/test_panel_control_plane_boundary.py`
  - Moves Feishu lifecycle handlers from transition to service-backed.
- Modify: `docs/phase3/panel-control-plane-boundary.md`
  - Records that panel Feishu lifecycle delegates to ChannelHub.
- Modify: `docs/phase3/phase-3-closure-status.md`
  - Updates Phase 4 progress note.

## Tasks

### Task 1: RED ChannelHub Feishu Lifecycle Tests

- [ ] **Step 1: Write failing hub tests**

Add tests for:

- `connect_feishu()` validates credentials.
- `connect_feishu()` persists Feishu config through `ConfigService`.
- `connect_feishu()` stops an existing adapter, creates a new adapter, starts it, stores it on `app.state.feishu_adapter`, and returns `{"ok": True, "connected": True}` when alive.
- `disconnect_feishu()` stops the adapter, clears app state, disables Feishu config, and returns `{"ok": True}`.
- `feishu_status()` returns the existing enabled/connected response shape.

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_channel_hub.py::test_channel_hub_connects_feishu_with_existing_response_shape tests/test_channel_hub.py::test_channel_hub_disconnects_feishu_and_disables_config tests/test_channel_hub.py::test_channel_hub_reports_feishu_status -q
```

Expected: FAIL because `ChannelHub` does not have Feishu lifecycle methods.

### Task 2: GREEN ChannelHub Feishu Lifecycle

- [ ] **Step 1: Implement hub lifecycle methods**

Use dependency injection:

- `config_service`
- `feishu_adapter_factory`
- `route_stream_func`

Default factory imports `FeishuAdapter`; default route function imports `agentmind.api.router.route_stream`.

- [ ] **Step 2: Run focused GREEN**

```bash
pytest tests/test_channel_hub.py -q
```

Expected: PASS.

### Task 3: RED Panel Delegation Tests

- [ ] **Step 1: Add panel delegation tests**

Monkeypatch `agentmind.panel.server.ChannelHub`, call:

- `POST /panel/api/feishu/connect`
- `POST /panel/api/feishu/disconnect`
- `GET /panel/api/feishu/status`

Assert panel returns hub results and passes app/request state to hub.

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_feishu_connect_uses_channel_hub tests/test_panel_api.py::TestPanelConfigServiceUsage::test_feishu_disconnect_uses_channel_hub tests/test_panel_api.py::TestPanelConfigServiceUsage::test_feishu_status_uses_channel_hub -q
```

Expected: FAIL because panel still owns Feishu lifecycle.

### Task 4: GREEN Panel Migration

- [ ] **Step 1: Migrate panel handlers**

Delegate:

- `feishu_connect`
- `feishu_disconnect`
- `feishu_status`

- [ ] **Step 2: Update boundary docs/tests**

Move Feishu lifecycle handlers to service-backed in panel boundary audit. The remaining direct Feishu lifecycle work is now startup and adapter internals, not panel handlers.

- [ ] **Step 3: Run focused GREEN**

```bash
pytest tests/test_channel_hub.py tests/test_panel_api.py::TestPanelConfigServiceUsage::test_feishu_connect_uses_channel_hub tests/test_panel_api.py::TestPanelConfigServiceUsage::test_feishu_disconnect_uses_channel_hub tests/test_panel_api.py::TestPanelConfigServiceUsage::test_feishu_status_uses_channel_hub tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py -q
```

Expected: PASS.

### Task 5: Verification

- [ ] **Step 1: Run channel/Feishu regression**

```bash
pytest tests/test_channel_hub.py tests/test_feishu_channel.py tests/test_feishu_path.py -q
```

- [ ] **Step 2: Run panel/architecture regression**

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py -q
```

- [ ] **Step 3: Run router/panel regression**

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

- [ ] **Step 4: Run full regression**

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
git add docs/superpowers/plans/2026-05-27-phase-4-feishu-lifecycle-channel-hub.md docs/phase3/panel-control-plane-boundary.md docs/phase3/phase-3-closure-status.md src/agentmind/channels/hub.py src/agentmind/panel/server.py tests/test_channel_hub.py tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py
git commit -m "refactor: route feishu lifecycle through channel hub"
```

## Self-Review

- Spec coverage: Covers panel Feishu lifecycle only.
- Placeholder scan: No TODO/TBD/fill-in markers.
- Architecture fit: Panel becomes an adapter for Feishu lifecycle, while startup and adapter internals remain explicit transition boundaries for later Phase 4 packages.
