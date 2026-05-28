# Feishu Route Callback Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the Feishu legacy `route_callback` fallback while preserving the standard `message_callback` / `ChannelMessage` inbound path.

**Architecture:** `ChannelHub` remains the owner of Feishu lifecycle and standard message routing glue. `FeishuAdapter` receives and processes `ChannelMessage` through `message_callback`; it no longer stores or executes `route_callback`. Panel/startup stay adapters, and no new Feishu business behavior is introduced.

**Tech Stack:** Python async channel adapter code, pytest, Markdown architecture docs.

---

## File Structure

- Modify: `tests/test_channel_hub.py`
  - Replace fallback-construction tests with tests proving ChannelHub no longer passes `route_callback`.
  - Keep standard `message_callback` / `ChannelMessage` tests green.
- Modify: `tests/test_feishu_channel.py`
  - Replace legacy fallback execution test with no-fallback behavior.
  - Keep standard callback behavior test green.
- Modify: `src/agentmind/channels/hub.py`
  - Remove `feishu_callback` construction and `_agentmind_compatibility_boundary`.
  - Stop passing `route_callback` to FeishuAdapter.
- Modify: `src/agentmind/channels/feishu.py`
  - Remove `route_callback` parameter, attribute, and fallback execution branch.
- Modify: `docs/phase4/feishu-route-callback-deletion-readiness.md`
  - Mark deletion as implemented.
- Modify: `docs/phase4/phase-4-closure-status.md`
  - Update compatibility boundary to say `feishu.route_callback` fallback has been removed.

No API/channel replay, observability UI, stream runtime replay, governance enforcement, customer-content inspection, TaskEventService schema change, SessionRuntimeService change, or Feishu business behavior expansion is in scope.

### Task 1: Add RED Tests for Deletion Behavior

**Files:**
- Modify: `tests/test_channel_hub.py`
- Modify: `tests/test_feishu_channel.py`

- [ ] **Step 1: Replace ChannelHub fallback tests**

In `tests/test_channel_hub.py`, replace `test_channel_hub_feishu_callback_provides_send_func_to_routing` with:

```python
@pytest.mark.asyncio
async def test_channel_hub_does_not_pass_feishu_route_callback():
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

    assert "route_callback" not in captured
    assert captured["message_callback"] is not None
```

Replace `test_channel_hub_marks_feishu_route_callback_as_migration_fallback` with:

```python
@pytest.mark.asyncio
async def test_channel_hub_feishu_adapter_kwargs_have_no_migration_fallback():
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

    assert "route_callback" not in captured
    assert not any(
        getattr(value, "_agentmind_compatibility_boundary", None)
        for value in captured.values()
    )
```

- [ ] **Step 2: Replace FeishuAdapter fallback test**

In `tests/test_feishu_channel.py`, replace `test_feishu_adapter_keeps_legacy_route_callback_fallback` with:

```python
    @pytest.mark.asyncio
    async def test_feishu_adapter_without_message_callback_does_not_route_legacy_fallback(self, monkeypatch):
        from agentmind.channels.feishu import FeishuAdapter

        adapter = FeishuAdapter("fake_id", "fake_secret")
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

        assert sent == [
            ("u1", "Agent 执行完成但未返回结果，请检查 Agent 配置或重试", "m1")
        ]
```

Update `test_feishu_adapter_prefers_standard_callback_over_legacy_fallback` so construction no longer passes `route_callback` and assertions no longer mention `legacy_calls`:

```python
    @pytest.mark.asyncio
    async def test_feishu_adapter_uses_standard_callback(self, monkeypatch):
        from agentmind.channels.feishu import FeishuAdapter

        standard_calls = []

        async def message_callback(message):
            standard_calls.append((message.sender_id, message.text))
            return ["standard reply"]

        adapter = FeishuAdapter(
            "fake_id",
            "fake_secret",
            message_callback=message_callback,
        )
        ...
        assert standard_calls == [("u1", "hello")]
        assert sent == [("u1", "standard reply", "m1")]
```

- [ ] **Step 3: Run RED**

Run:

```bash
pytest tests/test_channel_hub.py::test_channel_hub_does_not_pass_feishu_route_callback tests/test_channel_hub.py::test_channel_hub_feishu_adapter_kwargs_have_no_migration_fallback tests/test_feishu_channel.py::TestFeishuTextCleaning::test_feishu_adapter_without_message_callback_does_not_route_legacy_fallback tests/test_feishu_channel.py::TestFeishuTextCleaning::test_feishu_adapter_uses_standard_callback -q
```

Expected: FAIL because ChannelHub still passes `route_callback`, FeishuAdapter still stores/uses legacy fallback, or the renamed tests do not match current behavior.

### Task 2: Remove Production Fallback

**Files:**
- Modify: `src/agentmind/channels/hub.py`
- Modify: `src/agentmind/channels/feishu.py`

- [ ] **Step 1: Remove ChannelHub fallback construction**

In `src/agentmind/channels/hub.py`, remove:

```python
        route_stream_func = self._route_stream_func or self._default_route_stream_func
```

from `_create_feishu_adapter` if it is only used by `feishu_callback`.

Remove the entire `feishu_callback` nested function and `_agentmind_compatibility_boundary` assignment.

Change adapter construction to:

```python
        return adapter_factory(
            app_id=app_id,
            app_secret=app_secret,
            message_callback=feishu_message_callback,
        )
```

- [ ] **Step 2: Remove FeishuAdapter route_callback fallback**

In `src/agentmind/channels/feishu.py`, change constructor signature to:

```python
    def __init__(self, app_id: str, app_secret: str, message_callback=None):
```

Remove:

```python
        self.route_callback = route_callback
```

Remove the fallback branch:

```python
                    elif self.route_callback is not None:
                        async for chunk in self.route_callback(msg["text"], msg["sender_id"]):
                            full_output.append(chunk)
```

- [ ] **Step 3: Run GREEN focused**

Run:

```bash
pytest tests/test_channel_hub.py::test_channel_hub_does_not_pass_feishu_route_callback tests/test_channel_hub.py::test_channel_hub_feishu_adapter_kwargs_have_no_migration_fallback tests/test_feishu_channel.py::TestFeishuTextCleaning::test_feishu_adapter_without_message_callback_does_not_route_legacy_fallback tests/test_feishu_channel.py::TestFeishuTextCleaning::test_feishu_adapter_uses_standard_callback -q
```

Expected: PASS.

### Task 3: Update Readiness and Closure Docs

**Files:**
- Modify: `docs/phase4/feishu-route-callback-deletion-readiness.md`
- Modify: `docs/phase4/phase-4-closure-status.md`
- Modify: `tests/test_feishu_route_callback_deletion_readiness.py`

- [ ] **Step 1: Update deletion readiness test markers**

In `tests/test_feishu_route_callback_deletion_readiness.py`, replace markers for old fallback state with implemented deletion markers:

```python
    "`feishu.route_callback` fallback has been removed",
    "deleted in this package",
    "ChannelHub no longer constructs `route_callback`",
    "FeishuAdapter no longer executes `route_callback`",
    "standard inbound path uses `ChannelMessage`",
    "standard `message_callback` path remains supported",
```

Remove markers requiring:

```python
    "`feishu.route_callback` remains a bounded migration fallback",
    "not deleted in this package",
    "legacy fallback path still exists",
    "remove `route_callback` construction from ChannelHub",
    "remove fallback execution from FeishuAdapter",
    "remove legacy fallback tests deliberately",
```

Update the first test assertions accordingly:

```python
    assert "`feishu.route_callback` fallback has been removed" in text
    assert "deleted in this package" in text
```

- [ ] **Step 2: Update deletion readiness doc**

Change the readiness decision to:

```markdown
`feishu.route_callback` fallback has been removed and is deleted in this package.
```

Replace current/deletion blocker sections with:

```markdown
## Implemented Deletion

ChannelHub no longer constructs `route_callback`.

FeishuAdapter no longer executes `route_callback`.

The standard inbound path uses `ChannelMessage`.

The standard `message_callback` path remains supported.

Feishu discussion stop handling remains behind ChannelHub.
```

Keep explicit non-goals, but remove `no deletion in this package`.

- [ ] **Step 3: Update Phase 4 closure**

In `docs/phase4/phase-4-closure-status.md`, replace the compatibility boundary about `feishu.route_callback` with:

```markdown
- `feishu.route_callback` fallback has been removed; supported Feishu inbound handling uses `ChannelMessage`.
```

Update Next Direction text to avoid saying deletion readiness is pending:

```markdown
Feishu `route_callback` fallback deletion is complete in `docs/phase4/feishu-route-callback-deletion-readiness.md`.
```

- [ ] **Step 4: Run focused doc tests**

Run:

```bash
pytest tests/test_feishu_route_callback_deletion_readiness.py tests/test_phase4_closure_audit.py -q
```

Expected: PASS.

### Task 4: Run Required Regression Gates

**Files:**
- Read: all modified files

- [ ] **Step 1: Run focused tests**

Run:

```bash
pytest tests/test_channel_hub.py::test_channel_hub_does_not_pass_feishu_route_callback tests/test_channel_hub.py::test_channel_hub_feishu_adapter_kwargs_have_no_migration_fallback tests/test_feishu_channel.py::TestFeishuTextCleaning::test_feishu_adapter_without_message_callback_does_not_route_legacy_fallback tests/test_feishu_channel.py::TestFeishuTextCleaning::test_feishu_adapter_uses_standard_callback tests/test_feishu_route_callback_deletion_readiness.py -q
```

Expected: PASS.

- [ ] **Step 2: Run channel/feishu gate**

Run:

```bash
pytest tests/test_channel_hub.py tests/test_feishu_channel.py tests/test_feishu_path.py -q
```

Expected: PASS.

- [ ] **Step 3: Run panel/architecture gate**

Run:

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase5_closure_audit.py -q
```

Expected: PASS.

- [ ] **Step 4: Run router/panel regression**

Run:

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full verification**

Run:

```bash
pytest -q
git diff --check
git status --short
```

Expected: pytest PASS, diff check clean, status shows only intended changed files before commit.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/agentmind/channels/hub.py src/agentmind/channels/feishu.py tests/test_channel_hub.py tests/test_feishu_channel.py tests/test_feishu_route_callback_deletion_readiness.py docs/phase4/feishu-route-callback-deletion-readiness.md docs/phase4/phase-4-closure-status.md docs/superpowers/plans/2026-05-28-feishu-route-callback-deletion.md
git commit -m "refactor: remove feishu route callback fallback"
```

Expected: commit succeeds.

## Self-Review

- Spec coverage: the plan removes only legacy Feishu `route_callback` fallback while preserving standard `message_callback` / `ChannelMessage`.
- Placeholder scan: no TBD/TODO/implement-later placeholders remain.
- Scope check: no new Feishu business behavior, no channel replay, no observability UI, no stream runtime replay, no governance enforcement, no customer-content inspection, no TaskEventService schema change, and no SessionRuntimeService change is included.
