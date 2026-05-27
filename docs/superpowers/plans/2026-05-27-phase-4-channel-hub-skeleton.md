# Phase 4 ChannelHub Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first Phase 4 `ChannelHub` service boundary and standard channel models without changing existing Feishu behavior.

**Architecture:** `ChannelHub` owns channel registration, lifecycle calls, health/status views, and the standard `ChannelMessage` shape. Existing adapters remain infrastructure below the hub. In this package, panel `feishu_connect`/`feishu_disconnect`/`feishu_status`, startup auto-start, and `FeishuAdapter` internals stay unchanged as transition paths for the next packages.

**Tech Stack:** Python dataclasses, existing `ChannelAdapter`, pytest.

---

## Scope

Target in this package:

- Add `src/agentmind/channels/hub.py`.
- Add `tests/test_channel_hub.py`.
- Define standard models:
  - `ChannelMessage`
  - `ChannelStatus`
- Add `ChannelHub` methods:
  - `register_channel`
  - `start_channel`
  - `stop_channel`
  - `channel_status`
  - `list_statuses`
  - `dispatch_message`

Transition boundaries preserved:

- `panel/server.py::feishu_connect`
- `panel/server.py::feishu_disconnect`
- `panel/server.py::feishu_status`
- `startup.py::_maybe_start_feishu`
- `FeishuAdapter` route callback and message processing internals

Out of scope:

- Do not migrate Feishu lifecycle in this package.
- Do not create webhook/API channel implementations yet.
- Do not change `route_stream` usage.
- Do not change panel static UI.

## Files

- Create: `src/agentmind/channels/hub.py`
  - Contains dataclasses and `ChannelHub`.
- Modify: `src/agentmind/channels/__init__.py`
  - Exports `ChannelHub`, `ChannelMessage`, and `ChannelStatus`.
- Create: `tests/test_channel_hub.py`
  - Tests registration, lifecycle, status, and message dispatch.

## Tasks

### Task 1: RED ChannelHub Tests

- [ ] **Step 1: Write failing tests**

Add tests for:

- `ChannelMessage` carries channel id, sender id, text, raw payload, and metadata defaults.
- `ChannelHub.register_channel()` exposes initial status.
- `start_channel()` calls adapter `start()` and marks the channel enabled/connected.
- `stop_channel()` calls adapter `stop()` and marks the channel disconnected.
- `channel_status()` reports error when lifecycle calls fail.
- `dispatch_message()` sends the standard message to a registered async handler.

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_channel_hub.py -q
```

Expected: FAIL because `agentmind.channels.hub` does not exist.

### Task 2: GREEN ChannelHub Skeleton

- [ ] **Step 1: Implement models and hub**

Keep the implementation small:

- no Feishu-specific code;
- no config reads;
- no routing decisions;
- status in memory only.

- [ ] **Step 2: Run focused GREEN**

```bash
pytest tests/test_channel_hub.py -q
```

Expected: PASS.

### Task 3: Verification

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

### Task 4: Commit

- [ ] **Step 1: Check diff hygiene**

```bash
git diff --check
git status --short
```

- [ ] **Step 2: Review and commit**

```bash
git add docs/superpowers/plans/2026-05-27-phase-4-channel-hub-skeleton.md src/agentmind/channels/hub.py src/agentmind/channels/__init__.py tests/test_channel_hub.py
git commit -m "feat: add channel hub skeleton"
```

## Self-Review

- Spec coverage: Covers ChannelHub skeleton only.
- Placeholder scan: No TODO/TBD/fill-in markers.
- Architecture fit: Establishes service/channel boundary without making a long-term compromise for current panel/startup Feishu paths.
