# Phase 4 Feishu Message Standardization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Feishu inbound message processing toward the standard `ChannelMessage` boundary while keeping the existing route callback as a migration fallback.

**Architecture:** `FeishuAdapter` remains the protocol adapter: it receives Feishu events, extracts text, sends Feishu replies, and handles channel-level reactions. Inbound queue items become standard `ChannelMessage` objects. `ChannelHub` creates a standard Feishu message handler that owns the temporary routing glue to `route_stream`. The old `route_callback(msg, sender_id)` path stays as a compatibility fallback only when no standard message callback is configured.

**Tech Stack:** Python, `FeishuAdapter`, `ChannelHub`, pytest, pytest-asyncio.

---

## Scope

Target in this package:

- Add a standard message callback boundary to `FeishuAdapter`.
- Convert queued Feishu payloads to `ChannelMessage` before business dispatch.
- Add ChannelHub Feishu message-handler glue that routes a `ChannelMessage` through the existing `route_stream` path.
- Preserve the old `route_callback` generator as a migration fallback.
- Preserve channel-level behavior: reaction add/remove, final reply, empty-result reply, and error reply.

Out of scope:

- Do not remove `route_callback` yet.
- Do not move discussion stop-word rules in this package; they remain a known transition path inside `FeishuAdapter`.
- Do not change API/Webhook channels.
- Do not implement session persistence/recovery.
- Do not start Phase 5 CPE or AgentShield work.

## Files

- Modify: `src/agentmind/channels/feishu.py`
  - Accepts optional `message_callback`.
  - Adds `_to_channel_message()` conversion helper.
  - Dispatches standard `ChannelMessage` when callback exists.
  - Falls back to the legacy `route_callback`.
- Modify: `src/agentmind/channels/hub.py`
  - Adds `_handle_feishu_message()`.
  - Passes standard message callback into `FeishuAdapter`.
  - Keeps legacy route callback for compatibility.
- Modify: `tests/test_feishu_channel.py`
  - Adds RED coverage for conversion and standard callback dispatch.
  - Adds compatibility fallback coverage.
- Modify: `tests/test_channel_hub.py`
  - Adds RED coverage for ChannelHub Feishu standard handler glue.
- Modify: `docs/phase3/panel-control-plane-boundary.md`
  - Records Feishu inbound messages now enter through `ChannelMessage`.
- Modify: `docs/phase3/phase-3-closure-status.md`
  - Updates Phase 4 progress note.

## Tasks

### Task 1: RED FeishuAdapter Standard Message Boundary

**Files:**
- Modify: `tests/test_feishu_channel.py`

- [ ] **Step 1: Add failing conversion test**

Add this test:

```python
def test_feishu_adapter_converts_queue_payload_to_channel_message():
    from agentmind.channels.feishu import FeishuAdapter
    from agentmind.channels.hub import ChannelMessage

    adapter = FeishuAdapter("fake_id", "fake_secret", None)

    message = adapter._to_channel_message({
        "sender_id": "u1",
        "text": "hello",
        "msg_id": "m1",
    })

    assert isinstance(message, ChannelMessage)
    assert message.channel_id == "feishu"
    assert message.sender_id == "u1"
    assert message.text == "hello"
    assert message.raw_payload == {
        "sender_id": "u1",
        "text": "hello",
        "msg_id": "m1",
    }
    assert message.metadata == {"msg_id": "m1"}
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_feishu_channel.py::TestFeishuStandardMessage::test_feishu_adapter_converts_queue_payload_to_channel_message -q
```

Expected: FAIL because `FeishuAdapter` does not define `_to_channel_message`.

### Task 2: GREEN FeishuAdapter Conversion

**Files:**
- Modify: `src/agentmind/channels/feishu.py`

- [ ] **Step 1: Implement minimal conversion helper**

Add:

```python
    def _to_channel_message(self, msg: dict):
        from agentmind.channels.hub import ChannelMessage

        return ChannelMessage(
            channel_id="feishu",
            sender_id=str(msg.get("sender_id", "")),
            text=str(msg.get("text", "")),
            raw_payload=dict(msg),
            metadata={"msg_id": str(msg.get("msg_id", ""))},
        )
```

- [ ] **Step 2: Run GREEN**

Run:

```bash
pytest tests/test_feishu_channel.py::TestFeishuStandardMessage::test_feishu_adapter_converts_queue_payload_to_channel_message -q
```

Expected: PASS.

### Task 3: RED FeishuAdapter Standard Callback Dispatch

**Files:**
- Modify: `tests/test_feishu_channel.py`

- [ ] **Step 1: Add failing dispatch test**

Add this test:

```python
@pytest.mark.asyncio
async def test_feishu_adapter_processes_message_through_standard_callback(monkeypatch):
    from agentmind.channels.feishu import FeishuAdapter

    received = []

    async def message_callback(message):
        received.append(message)
        return ["standard ", "reply"]

    adapter = FeishuAdapter("fake_id", "fake_secret", None, message_callback=message_callback)
    await adapter._message_queue.put({"sender_id": "u1", "text": "hello", "msg_id": "m1"})
    sent = []
    reactions = []

    async def add_reaction(msg_id, emoji_type="MUSCLE"):
        reactions.append(("add", msg_id, emoji_type))
        return "r1"

    async def remove_reaction(msg_id, reaction_id):
        reactions.append(("remove", msg_id, reaction_id))

    async def send_message(user_id, content, root_msg_id=""):
        sent.append((user_id, content, root_msg_id))
        adapter._main_loop_task.cancel()

    monkeypatch.setattr(adapter, "_add_reaction", add_reaction)
    monkeypatch.setattr(adapter, "_remove_reaction", remove_reaction)
    monkeypatch.setattr(adapter, "send_message", send_message)

    adapter._main_loop_task = asyncio.create_task(adapter._process_messages())
    await adapter._main_loop_task

    assert received[0].channel_id == "feishu"
    assert received[0].sender_id == "u1"
    assert received[0].text == "hello"
    assert received[0].metadata == {"msg_id": "m1"}
    assert reactions == [("add", "m1", "MUSCLE"), ("remove", "m1", "r1")]
    assert sent == [("u1", "standard reply", "m1")]
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_feishu_channel.py::TestFeishuStandardMessage::test_feishu_adapter_processes_message_through_standard_callback -q
```

Expected: FAIL because `FeishuAdapter.__init__` does not accept `message_callback`.

### Task 4: GREEN FeishuAdapter Standard Callback With Legacy Fallback

**Files:**
- Modify: `src/agentmind/channels/feishu.py`
- Modify: `tests/test_feishu_channel.py`

- [ ] **Step 1: Implement standard callback support**

Change constructor signature to:

```python
def __init__(self, app_id: str, app_secret: str, route_callback=None, message_callback=None):
```

Store `self.message_callback = message_callback`.

In `_process_messages()`, after reaction is added:

```python
full_output = []
channel_message = self._to_channel_message(msg)
if self.message_callback is not None:
    result = await self.message_callback(channel_message)
    if result is None:
        full_output = []
    elif isinstance(result, str):
        full_output = [result]
    else:
        full_output = [str(chunk) for chunk in result]
elif self.route_callback is not None:
    async for chunk in self.route_callback(msg["text"], msg["sender_id"]):
        full_output.append(chunk)
else:
    full_output = []
```

- [ ] **Step 2: Add legacy fallback test**

Add this test:

```python
@pytest.mark.asyncio
async def test_feishu_adapter_keeps_legacy_route_callback_fallback(monkeypatch):
    from agentmind.channels.feishu import FeishuAdapter

    calls = []

    async def route_callback(text, sender_id):
        calls.append((text, sender_id))
        yield "legacy reply"

    adapter = FeishuAdapter("fake_id", "fake_secret", route_callback)
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

    assert calls == [("hello", "u1")]
    assert sent == [("u1", "legacy reply", "m1")]
```

- [ ] **Step 3: Run focused GREEN**

Run:

```bash
pytest tests/test_feishu_channel.py::TestFeishuStandardMessage -q
```

Expected: PASS.

### Task 5: RED ChannelHub Feishu Message Handler Glue

**Files:**
- Modify: `tests/test_channel_hub.py`

- [ ] **Step 1: Add failing hub glue test**

Add this test:

```python
@pytest.mark.asyncio
async def test_channel_hub_feishu_standard_message_handler_routes_channel_message():
    from agentmind.channels.hub import ChannelHub, ChannelMessage

    app = _App()
    adapter = _Adapter()
    captured = {}
    route_calls = []

    def adapter_factory(**kwargs):
        captured.update(kwargs)
        return adapter

    async def route_stream_func(*args, **kwargs):
        route_calls.append((args, kwargs))
        await kwargs["send_func"]("side effect reply")
        yield "main "
        yield "reply"

    hub = ChannelHub(
        config_service=_ConfigService(),
        feishu_adapter_factory=adapter_factory,
        route_stream_func=route_stream_func,
    )
    await hub.connect_feishu(app, "app", "secret")

    result = await captured["message_callback"](
        ChannelMessage(
            channel_id="feishu",
            sender_id="u1",
            text="hello",
            metadata={"msg_id": "m1"},
        )
    )

    assert result == ["main ", "reply"]
    assert route_calls[0][0][:5] == (
        "hello",
        "u1",
        app.state.agent_registry,
        app.state.rule_engine,
        app.state.settings,
    )
    assert adapter.sent == [("u1", "side effect reply")]
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_channel_hub.py::test_channel_hub_feishu_standard_message_handler_routes_channel_message -q
```

Expected: FAIL because ChannelHub does not pass `message_callback` to the adapter.

### Task 6: GREEN ChannelHub Standard Feishu Glue

**Files:**
- Modify: `src/agentmind/channels/hub.py`

- [ ] **Step 1: Implement `_handle_feishu_message()`**

Add a method that:

- accepts `app` and `ChannelMessage`;
- creates the same `send_func` used by the legacy callback;
- calls `route_stream_func(message.text, message.sender_id, registry, rule_engine, settings, send_func=_send)`;
- collects and returns a list of chunks.

- [ ] **Step 2: Pass `message_callback` into adapter factory**

In `_create_feishu_adapter()`, pass both:

```python
route_callback=feishu_callback,
message_callback=feishu_message_callback,
```

The legacy callback remains for old adapters and rollback safety.

- [ ] **Step 3: Run focused GREEN**

Run:

```bash
pytest tests/test_channel_hub.py::test_channel_hub_feishu_standard_message_handler_routes_channel_message tests/test_channel_hub.py::test_channel_hub_feishu_callback_provides_send_func_to_routing -q
```

Expected: PASS.

### Task 7: Architecture Notes

**Files:**
- Modify: `docs/phase3/panel-control-plane-boundary.md`
- Modify: `docs/phase3/phase-3-closure-status.md`

- [ ] **Step 1: Update docs**

Record:

- Feishu inbound messages now convert to standard `ChannelMessage` before business dispatch.
- ChannelHub owns the Feishu routing glue for standard messages.
- Legacy `route_callback` remains as a migration fallback and must not be treated as the long-term boundary.
- Discussion stop-word handling remains a later Phase 4 migration item.

### Task 8: Strict Verification

- [ ] **Step 1: Run focused tests**

```bash
pytest tests/test_feishu_channel.py::TestFeishuStandardMessage tests/test_channel_hub.py::test_channel_hub_feishu_standard_message_handler_routes_channel_message -q
pytest tests/test_channel_hub.py tests/test_feishu_channel.py -q
```

- [ ] **Step 2: Run Feishu/channel regression**

```bash
pytest tests/test_startup.py tests/test_channel_hub.py tests/test_feishu_channel.py tests/test_feishu_path.py -q
```

- [ ] **Step 3: Run panel/architecture regression**

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py -q
```

- [ ] **Step 4: Run router/panel regression**

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

- [ ] **Step 5: Run full verification**

```bash
pytest -q
git diff --check
git status --short
```

### Task 9: Commit

- [ ] **Step 1: Review diff and commit**

```bash
git add docs/superpowers/plans/2026-05-27-phase-4-feishu-message-standardization.md docs/phase3/panel-control-plane-boundary.md docs/phase3/phase-3-closure-status.md src/agentmind/channels/feishu.py src/agentmind/channels/hub.py tests/test_feishu_channel.py tests/test_channel_hub.py
git commit -m "refactor: standardize feishu channel messages"
```

## Self-Review

- Spec coverage: Covers the first FeishuAdapter message-processing standardization package only.
- Placeholder scan: No TBD/TODO/fill-in markers.
- Type consistency: Uses existing `ChannelMessage`, `ChannelHub`, and `FeishuAdapter` names.
- Migration fit: Standard message callback becomes the preferred path; legacy callback remains only as compatibility fallback.
