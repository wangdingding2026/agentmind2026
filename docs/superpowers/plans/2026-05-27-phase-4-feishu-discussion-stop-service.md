# Phase 4 Feishu Discussion Stop Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Feishu discussion stop-word handling out of `FeishuAdapter` and into the ChannelHub/service message boundary.

**Architecture:** `FeishuAdapter` remains a protocol adapter: receive Feishu events, normalize payloads into `ChannelMessage`, add/remove channel-level reactions, and send Feishu replies. `ChannelHub` owns the temporary Feishu discussion-stop glue by checking `ChannelMessage` text against the existing stop-word rule, calling `session_registry`, and returning the stop acknowledgement before routing. Normal messages continue through `route_stream`, and the legacy `route_callback` remains only as a compatibility fallback when no standard message callback exists.

**Tech Stack:** Python, `FeishuAdapter`, `ChannelHub`, `ChannelMessage`, pytest, pytest-asyncio.

---

## Scope

Target in this package:

- Remove discussion stop-word business logic from `FeishuAdapter._process_messages()`.
- Keep `FeishuAdapter` standard callback dispatch as the only new-path business boundary.
- Add ChannelHub standard Feishu message handling for stop words:
  - stop words are `["停", "stop", "结束", "终止", "end"]`;
  - a stop word matches when it appears in lowercased stripped text and text length is at most 10;
  - active discussion is checked through `session_registry.is_discussion_active(sender_id)`;
  - active discussion is stopped through `session_registry.stop_discussion(sender_id)`;
  - handler returns `["正在结束讨论..."]` so the adapter replies in the original thread.
- Preserve normal Feishu messages through `route_stream`.
- Preserve legacy `route_callback(msg, sender_id)` fallback only when no standard message callback is configured.

Out of scope:

- Do not remove `route_callback`.
- Do not migrate API/Webhook channels.
- Do not change routing discussion loop internals.
- Do not implement session persistence/recovery.
- Do not migrate shutdown adapter stop behavior.
- Do not start Phase 5 CPE or AgentShield work.

## Files

- Modify: `tests/test_feishu_channel.py`
  - Add RED coverage proving a stop-word message is delivered to `message_callback` and does not bypass the standard boundary inside `FeishuAdapter`.
- Modify: `tests/test_channel_hub.py`
  - Add RED coverage proving ChannelHub handles Feishu stop words through `ChannelMessage`, stops active discussions, returns the stop acknowledgement, and does not call `route_stream`.
  - Add/keep coverage proving normal Feishu messages still call `route_stream`.
- Modify: `src/agentmind/channels/feishu.py`
  - Remove direct `session_registry` import and stop-word handling from `_process_messages()`.
- Modify: `src/agentmind/channels/hub.py`
  - Add small Feishu discussion-stop helper logic under `_handle_feishu_message()`.
- Modify: `docs/phase3/panel-control-plane-boundary.md`
  - Update boundary note so Feishu discussion stop-word handling is no longer listed as an adapter transition path.
- Modify: `docs/phase3/phase-3-closure-status.md`
  - Record the Phase 4 package completion and next migration direction.

## Tasks

### Task 1: RED FeishuAdapter Stop Words Use Standard Callback

**Files:**
- Modify: `tests/test_feishu_channel.py`

- [ ] **Step 1: Add failing adapter boundary test**

Add this test under `TestFeishuStandardMessage`:

```python
@pytest.mark.asyncio
async def test_feishu_adapter_sends_stop_words_to_standard_callback(self, monkeypatch):
    from agentmind.channels.feishu import FeishuAdapter
    from agentmind.routing.side_effects.session_registry import session_registry

    session_registry.start_discussion("u1")
    received = []

    async def message_callback(message):
        received.append(message)
        return ["callback handled stop"]

    adapter = FeishuAdapter("fake_id", "fake_secret", None, message_callback=message_callback)
    await adapter._message_queue.put({"sender_id": "u1", "text": "stop", "msg_id": "m1"})
    sent = []

    async def send_message(user_id, content, root_msg_id=""):
        sent.append((user_id, content, root_msg_id))
        adapter._main_loop_task.cancel()

    monkeypatch.setattr(adapter, "_add_reaction", AsyncMock(return_value="r1"))
    monkeypatch.setattr(adapter, "_remove_reaction", AsyncMock())
    monkeypatch.setattr(adapter, "send_message", send_message)

    try:
        adapter._main_loop_task = asyncio.create_task(adapter._process_messages())
        await adapter._main_loop_task
    finally:
        session_registry.end_discussion("u1")

    assert [(message.sender_id, message.text) for message in received] == [("u1", "stop")]
    assert sent == [("u1", "callback handled stop", "m1")]
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_feishu_channel.py::TestFeishuStandardMessage::test_feishu_adapter_sends_stop_words_to_standard_callback -q
```

Expected: FAIL because `FeishuAdapter._process_messages()` handles the stop word before `message_callback`.

### Task 2: RED ChannelHub Handles Feishu Discussion Stop

**Files:**
- Modify: `tests/test_channel_hub.py`

- [ ] **Step 1: Add failing ChannelHub stop-word test**

Add this test:

```python
@pytest.mark.asyncio
async def test_channel_hub_feishu_standard_message_handler_stops_active_discussion():
    from agentmind.channels.hub import ChannelHub, ChannelMessage
    from agentmind.routing.side_effects.session_registry import session_registry

    app = _App()
    adapter = _Adapter()
    captured = {}
    route_calls = []

    def adapter_factory(**kwargs):
        captured.update(kwargs)
        return adapter

    async def route_stream_func(*args, **kwargs):
        route_calls.append((args, kwargs))
        yield "should not route"

    hub = ChannelHub(
        config_service=_ConfigService(),
        feishu_adapter_factory=adapter_factory,
        route_stream_func=route_stream_func,
    )
    await hub.connect_feishu(app, "app", "secret")

    session_registry.start_discussion("u1")
    try:
        result = await captured["message_callback"](
            ChannelMessage(channel_id="feishu", sender_id="u1", text="stop")
        )
    finally:
        session_registry.end_discussion("u1")

    assert result == ["正在结束讨论..."]
    assert route_calls == []
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_channel_hub.py::test_channel_hub_feishu_standard_message_handler_stops_active_discussion -q
```

Expected: FAIL because ChannelHub currently routes every standard Feishu message through `route_stream`.

### Task 3: GREEN Move Stop Rule Into ChannelHub

**Files:**
- Modify: `src/agentmind/channels/feishu.py`
- Modify: `src/agentmind/channels/hub.py`

- [ ] **Step 1: Remove adapter business rule block**

In `src/agentmind/channels/feishu.py`, remove this block from `_process_messages()`:

```python
# 讨论模式停止信号检测（模糊匹配）
msg_text = str(msg.get("text", "")).strip().lower()
stop_words = ["停", "stop", "结束", "终止", "end"]
is_stop = any(w in msg_text for w in stop_words) and len(msg_text) <= 10
if is_stop:
    from agentmind.routing.side_effects.session_registry import session_registry
    if session_registry.is_discussion_active(msg["sender_id"]):
        session_registry.stop_discussion(msg["sender_id"])
        await self.send_message(msg["sender_id"], "正在结束讨论...")
        continue
```

Keep `msg_text` inside the routing try block:

```python
msg_text = str(msg.get("text", "")).strip().lower()
```

- [ ] **Step 2: Add ChannelHub stop helpers and branch**

In `src/agentmind/channels/hub.py`, add these methods to `ChannelHub`:

```python
    def _handle_feishu_discussion_stop(self, message: ChannelMessage) -> list[str] | None:
        if not self._is_discussion_stop_message(message.text):
            return None

        from agentmind.routing.side_effects.session_registry import session_registry

        if not session_registry.is_discussion_active(message.sender_id):
            return None

        session_registry.stop_discussion(message.sender_id)
        return ["正在结束讨论..."]

    @staticmethod
    def _is_discussion_stop_message(text: str) -> bool:
        msg_text = str(text).strip().lower()
        stop_words = ["停", "stop", "结束", "终止", "end"]
        return any(word in msg_text for word in stop_words) and len(msg_text) <= 10
```

At the top of `_handle_feishu_message()`, add:

```python
        stop_result = self._handle_feishu_discussion_stop(message)
        if stop_result is not None:
            return stop_result
```

- [ ] **Step 3: Run GREEN focused tests**

Run:

```bash
pytest tests/test_feishu_channel.py::TestFeishuStandardMessage::test_feishu_adapter_sends_stop_words_to_standard_callback tests/test_channel_hub.py::test_channel_hub_feishu_standard_message_handler_stops_active_discussion -q
```

Expected: 2 passed.

### Task 4: Regression Coverage For Normal Routing And Legacy Fallback

**Files:**
- Existing tests only unless a failure reveals a missing assertion.

- [ ] **Step 1: Run standard-message adapter tests**

Run:

```bash
pytest tests/test_feishu_channel.py::TestFeishuStandardMessage -q
```

Expected: All tests in `TestFeishuStandardMessage` pass, including legacy fallback.

- [ ] **Step 2: Run ChannelHub standard Feishu tests**

Run:

```bash
pytest tests/test_channel_hub.py::test_channel_hub_feishu_standard_message_handler_routes_channel_message tests/test_channel_hub.py::test_channel_hub_feishu_standard_message_handler_stops_active_discussion -q
```

Expected: 2 passed. The normal message test proves `route_stream` still receives non-stop messages.

### Task 5: Documentation Update

**Files:**
- Modify: `docs/phase3/panel-control-plane-boundary.md`
- Modify: `docs/phase3/phase-3-closure-status.md`

- [ ] **Step 1: Update panel boundary note**

Replace:

```markdown
- Feishu discussion stop-word handling is still a transition path below the panel and should move behind the channel/service message boundary in a later Phase 4 package.
```

with:

```markdown
- Feishu discussion stop-word handling now lives behind the `ChannelHub` standard message boundary; `FeishuAdapter` no longer owns the session stop rule.
```

- [ ] **Step 2: Update Phase 3 closure status**

In Phase 4 completed package list, add:

```markdown
7. Moved Feishu discussion stop-word handling out of `FeishuAdapter` and behind the `ChannelHub` standard message boundary.
```

Replace the next-step paragraph with:

```markdown
Next, continue moving remaining channel runtime concerns behind service/channel boundaries. The preferred next package is persistence/recovery for session and stream runtime state. That work should build on `SessionRuntimeService`; it should not move runtime state back into panel.
```

### Task 6: Strict Verification And Commit

**Files:**
- All modified files.

- [ ] **Step 1: Run focused tests**

Run:

```bash
pytest tests/test_feishu_channel.py::TestFeishuStandardMessage tests/test_channel_hub.py -q
```

Expected: pass.

- [ ] **Step 2: Run Feishu/channel regression**

Run:

```bash
pytest tests/test_startup.py tests/test_channel_hub.py tests/test_feishu_channel.py tests/test_feishu_path.py -q
```

Expected: pass.

- [ ] **Step 3: Run panel/architecture regression**

Run:

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py -q
```

Expected: pass.

- [ ] **Step 4: Run router/panel regression**

Run:

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

Expected: pass.

- [ ] **Step 5: Run full suite**

Run:

```bash
pytest -q
```

Expected: pass.

- [ ] **Step 6: Run diff and status checks**

Run:

```bash
git diff --check
git status --short
```

Expected: `git diff --check` has no output. `git status --short` shows only the planned files before commit.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/agentmind/channels/feishu.py src/agentmind/channels/hub.py tests/test_feishu_channel.py tests/test_channel_hub.py docs/phase3/panel-control-plane-boundary.md docs/phase3/phase-3-closure-status.md docs/superpowers/plans/2026-05-27-phase-4-feishu-discussion-stop-service.md
git commit -m "refactor: route feishu discussion stop through channel hub"
```

Expected: commit succeeds.

## Self-Review

- Spec coverage: Covers only the Feishu discussion stop-word migration package and leaves API/Webhook, persistence, shutdown, and Phase 5 out of scope.
- Placeholder scan: No TODO/TBD placeholders are present.
- Type consistency: Uses existing `ChannelMessage`, `ChannelHub`, `FeishuAdapter`, `session_registry`, and pytest names.
- Architecture fit: Moves business rule handling from adapter into the standard channel/service message boundary without making the legacy callback the new rules carrier.
