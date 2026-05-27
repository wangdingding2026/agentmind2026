# Phase 4 ChannelHub Compatibility Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the remaining Feishu `route_callback` compatibility path explicit, auditable, and bounded for later deletion.

**Architecture:** `FeishuAdapter` keeps accepting `route_callback` only as a migration fallback when no standard `message_callback` is configured. `ChannelHub` continues to provide both callbacks during migration, but the legacy callback must be marked as compatibility-only and must not own Feishu business rules. Documentation records deletion criteria so Phase 4 can close without turning fallback code into a permanent architecture dependency.

**Tech Stack:** Python, `ChannelHub`, `FeishuAdapter`, `ChannelMessage`, pytest, pytest-asyncio, markdown architecture audits.

---

## Scope

Target in this package:

- Keep standard Feishu inbound messages on `ChannelMessage` and `message_callback`.
- Keep legacy `route_callback(msg, sender_id)` available only as fallback/migration support.
- Add a small compatibility marker to the legacy Feishu callback created by `ChannelHub`.
- Add tests that enforce:
  - standard callback is still preferred by `FeishuAdapter` when both callbacks exist;
  - `ChannelHub` marks the old callback as a migration fallback;
  - architecture docs state the fallback deletion criteria.
- Update Phase 3/4 boundary docs with explicit removal criteria.

Out of scope:

- Do not delete `route_callback` in this package.
- Do not move API/Webhook channels.
- Do not change discussion stop-word behavior except to verify it remains behind standard messages.
- Do not implement persistent task-event replay.
- Do not start Phase 5 CPE or AgentShield work.

## Files

- Modify: `tests/test_feishu_channel.py`
  - Add RED coverage proving standard `message_callback` wins when both callbacks are configured.
- Modify: `tests/test_channel_hub.py`
  - Add RED coverage proving ChannelHub marks the legacy Feishu callback as a migration fallback.
- Modify: `tests/test_phase3_closure_audit.py`
  - Add RED coverage proving docs name the legacy fallback and its deletion criteria.
- Modify: `src/agentmind/channels/hub.py`
  - Mark the legacy Feishu callback with compatibility metadata when it is created.
- Modify: `docs/phase3/phase-3-closure-status.md`
  - Record the compatibility cleanup and deletion criteria.
- Modify: `docs/phase3/panel-control-plane-boundary.md`
  - Record the compatibility-only role of Feishu `route_callback`.

## Tasks

### Task 1: RED Standard Callback Precedence

**Files:**
- Modify: `tests/test_feishu_channel.py`

- [ ] **Step 1: Write the failing/guardrail test**

Add this test under `TestFeishuStandardMessage`:

```python
@pytest.mark.asyncio
async def test_feishu_adapter_prefers_standard_callback_over_legacy_fallback(self, monkeypatch):
    from agentmind.channels.feishu import FeishuAdapter

    standard_calls = []
    legacy_calls = []

    async def message_callback(message):
        standard_calls.append((message.sender_id, message.text))
        return ["standard reply"]

    async def route_callback(text, sender_id):
        legacy_calls.append((text, sender_id))
        yield "legacy reply"

    adapter = FeishuAdapter(
        "fake_id",
        "fake_secret",
        route_callback=route_callback,
        message_callback=message_callback,
    )
    await adapter._message_queue.put({"sender_id": "u1", "text": "hello", "msg_id": "m1"})
    sent = []

    async def send_message(user_id, content, root_msg_id=""):
        sent.append((user_id, content, root_msg_id))
        adapter._main_loop_task.cancel()

    monkeypatch.setattr(adapter, "_add_reaction", AsyncMock(return_value="r1"))
    monkeypatch.setattr(adapter, "_remove_reaction", AsyncMock())
    monkeypatch.setattr(adapter, "send_message", send_message)

    adapter._main_loop_task = asyncio.create_task(adapter._process_messages())
    await adapter._main_loop_task

    assert standard_calls == [("u1", "hello")]
    assert legacy_calls == []
    assert sent == [("u1", "standard reply", "m1")]
```

- [ ] **Step 2: Run RED/guardrail**

Run:

```bash
pytest tests/test_feishu_channel.py::TestFeishuStandardMessage::test_feishu_adapter_prefers_standard_callback_over_legacy_fallback -q
```

Expected: PASS if the previous package already established precedence. If it passes, keep it as a regression guardrail and use Task 2/3 as the RED tests for this cleanup.

### Task 2: RED ChannelHub Marks Legacy Callback

**Files:**
- Modify: `tests/test_channel_hub.py`

- [ ] **Step 1: Add failing compatibility marker test**

Add this test:

```python
@pytest.mark.asyncio
async def test_channel_hub_marks_feishu_route_callback_as_migration_fallback():
    from agentmind.channels.hub import ChannelHub

    app = _App()
    captured = {}

    def adapter_factory(**kwargs):
        captured.update(kwargs)
        return _Adapter()

    async def route_stream_func(*args, **kwargs):
        yield "ok"

    hub = ChannelHub(
        config_service=_ConfigService(),
        feishu_adapter_factory=adapter_factory,
        route_stream_func=route_stream_func,
    )
    await hub.connect_feishu(app, "app", "secret")

    legacy_callback = captured["route_callback"]
    assert getattr(legacy_callback, "_agentmind_compatibility_boundary", None) == {
        "name": "feishu.route_callback",
        "status": "migration_fallback",
        "delete_after": "Feishu inbound handling no longer needs route_callback fallback",
    }
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_channel_hub.py::test_channel_hub_marks_feishu_route_callback_as_migration_fallback -q
```

Expected: FAIL because the legacy callback is not yet marked.

### Task 3: RED Documentation Deletion Criteria

**Files:**
- Modify: `tests/test_phase3_closure_audit.py`

- [ ] **Step 1: Add failing architecture audit**

Add this test:

```python
def test_phase4_feishu_route_callback_fallback_has_deletion_criteria():
    docs = "\n".join([
        PHASE3_DOC.read_text(encoding="utf-8"),
        PANEL_BOUNDARY_DOC.read_text(encoding="utf-8"),
    ])

    assert "feishu.route_callback" in docs
    assert "migration fallback" in docs
    assert "delete after" in docs.lower()
    assert "ChannelMessage" in docs
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_phase3_closure_audit.py::test_phase4_feishu_route_callback_fallback_has_deletion_criteria -q
```

Expected: FAIL because docs do not yet state explicit deletion criteria for `feishu.route_callback`.

### Task 4: GREEN Compatibility Marker And Docs

**Files:**
- Modify: `src/agentmind/channels/hub.py`
- Modify: `docs/phase3/phase-3-closure-status.md`
- Modify: `docs/phase3/panel-control-plane-boundary.md`

- [ ] **Step 1: Add the legacy callback marker**

In `ChannelHub._create_feishu_adapter()`, after defining `feishu_callback`, set:

```python
        feishu_callback._agentmind_compatibility_boundary = {
            "name": "feishu.route_callback",
            "status": "migration_fallback",
            "delete_after": "Feishu inbound handling no longer needs route_callback fallback",
        }
```

- [ ] **Step 2: Update docs**

Add text to the Phase 3 closure and panel boundary docs stating:

```text
`feishu.route_callback` is a migration fallback only. Delete after Feishu inbound handling no longer needs `route_callback` fallback and all supported Feishu inbound paths use `ChannelMessage`.
```

- [ ] **Step 3: Run GREEN focused tests**

Run:

```bash
pytest tests/test_channel_hub.py::test_channel_hub_marks_feishu_route_callback_as_migration_fallback tests/test_phase3_closure_audit.py::test_phase4_feishu_route_callback_fallback_has_deletion_criteria -q
```

Expected: 2 passed.

### Task 5: Regression And Verification

**Files:**
- Existing test suites.

- [ ] **Step 1: Focused Feishu/ChannelHub tests**

Run:

```bash
pytest tests/test_feishu_channel.py::TestFeishuStandardMessage tests/test_channel_hub.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Feishu/channel regression**

Run:

```bash
pytest tests/test_startup.py tests/test_channel_hub.py tests/test_feishu_channel.py tests/test_feishu_path.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Panel/architecture regression**

Run:

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py -q
```

Expected: all selected tests pass.

- [ ] **Step 4: Router/panel regression**

Run:

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Full verification**

Run:

```bash
pytest -q
git diff --check
git status --short
```

Expected: full pytest passes, whitespace check is clean, and git status only shows this package's intended files before commit.

### Task 6: Commit

**Files:**
- Stage only files changed by this package.

- [ ] **Step 1: Review diff**

Run:

```bash
git diff -- src/agentmind/channels/hub.py tests/test_feishu_channel.py tests/test_channel_hub.py tests/test_phase3_closure_audit.py docs/phase3/phase-3-closure-status.md docs/phase3/panel-control-plane-boundary.md docs/superpowers/plans/2026-05-27-phase-4-channel-hub-compatibility-cleanup.md
```

- [ ] **Step 2: Commit**

Run:

```bash
git add src/agentmind/channels/hub.py tests/test_feishu_channel.py tests/test_channel_hub.py tests/test_phase3_closure_audit.py docs/phase3/phase-3-closure-status.md docs/phase3/panel-control-plane-boundary.md docs/superpowers/plans/2026-05-27-phase-4-channel-hub-compatibility-cleanup.md
git commit -m "refactor: mark feishu fallback compatibility boundary"
```

## Self-Review

- The package does not delete `route_callback`, so it preserves migration compatibility.
- The package does not add business rules to the fallback path.
- The package adds a code-level compatibility marker and documentation deletion criteria.
- The package keeps tests focused on new architecture goals, not only old behavior.
