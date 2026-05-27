# Phase 4 Startup Feishu ChannelHub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move startup Feishu auto-start out of `startup.py` and into `ChannelHub`, so application startup delegates channel lifecycle work to the channel service boundary.

**Architecture:** `startup.py` remains a lifecycle adapter: it reads app settings, starts background tasks, and delegates Feishu channel startup. `ChannelHub` owns the rule for whether Feishu should auto-start and the execution path that calls the existing Feishu lifecycle connector. Existing FeishuAdapter internals remain unchanged in this package; they are a transition boundary for the next package.

**Tech Stack:** Python, FastAPI lifespan, pytest, pytest-asyncio.

---

### Task 1: Add ChannelHub Auto-Start Contract

**Files:**
- Modify: `tests/test_channel_hub.py`
- Modify: `src/agentmind/channels/hub.py`

- [ ] **Step 1: Write the failing tests**

Add tests that describe the service-layer behavior:

```python
@pytest.mark.asyncio
async def test_channel_hub_skips_feishu_auto_start_when_config_disabled():
    from agentmind.channels.hub import ChannelHub

    app = _App()
    hub = ChannelHub(config_service=_ConfigService())

    result = await hub.maybe_start_feishu(
        app,
        {"feishu": {"enabled": False, "app_id": "app", "app_secret": "secret"}},
    )

    assert result is None
    assert not hasattr(app.state, "feishu_adapter")


@pytest.mark.asyncio
async def test_channel_hub_auto_starts_feishu_from_settings():
    from agentmind.channels.hub import ChannelHub

    app = _App()
    config_service = _ConfigService()
    created = []

    def adapter_factory(**kwargs):
        created.append(kwargs)
        return _Adapter()

    async def route_stream_func(*args, **kwargs):
        yield "ok"

    hub = ChannelHub(
        config_service=config_service,
        feishu_adapter_factory=adapter_factory,
        route_stream_func=route_stream_func,
    )

    result = await hub.maybe_start_feishu(
        app,
        {"feishu": {"enabled": True, "app_id": " app ", "app_secret": " secret "}},
    )

    assert result is app.state.feishu_adapter
    assert result.started == 1
    assert created[0]["app_id"] == "app"
    assert created[0]["app_secret"] == "secret"
```

- [ ] **Step 2: Run tests to verify RED**

Run: `pytest tests/test_channel_hub.py::test_channel_hub_skips_feishu_auto_start_when_config_disabled tests/test_channel_hub.py::test_channel_hub_auto_starts_feishu_from_settings -q`

Expected: FAIL because `ChannelHub` does not define `maybe_start_feishu`.

- [ ] **Step 3: Implement minimal ChannelHub method**

Add `maybe_start_feishu(self, app, settings)` to `ChannelHub`.

The method should:
- read `settings["feishu"]` only when `settings` is a dict;
- return `None` when enabled/app_id/app_secret are missing;
- call `connect_feishu(app, app_id, app_secret)` for the actual lifecycle work;
- return `app.state.feishu_adapter` only when connect succeeds;
- return `None` on connect failure.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `pytest tests/test_channel_hub.py::test_channel_hub_skips_feishu_auto_start_when_config_disabled tests/test_channel_hub.py::test_channel_hub_auto_starts_feishu_from_settings -q`

Expected: PASS.

### Task 2: Delegate Startup Auto-Start To ChannelHub

**Files:**
- Modify: `tests/test_startup.py`
- Modify: `src/agentmind/startup.py`

- [ ] **Step 1: Write the failing startup delegation test**

Add a test proving `startup._maybe_start_feishu` delegates to `ChannelHub`:

```python
def test_startup_maybe_start_feishu_delegates_to_channel_hub(monkeypatch):
    import asyncio
    import agentmind.startup as startup

    calls = []

    class FakeHub:
        def __init__(self, config_service):
            self.config_service = config_service

        async def maybe_start_feishu(self, app, settings):
            calls.append((self.config_service, app, settings))
            return "adapter"

    app = type("App", (), {"state": object()})()
    config_service = object()
    settings = {"feishu": {"enabled": True, "app_id": "app", "app_secret": "secret"}}
    monkeypatch.setattr(startup, "ChannelHub", FakeHub)

    result = asyncio.run(
        startup._maybe_start_feishu(app, settings, config_service=config_service)
    )

    assert result == "adapter"
    assert calls == [(config_service, app, settings)]
```

- [ ] **Step 2: Run test to verify RED**

Run: `pytest tests/test_startup.py::test_startup_maybe_start_feishu_delegates_to_channel_hub -q`

Expected: FAIL because `_maybe_start_feishu` does not accept `config_service` and does not instantiate `ChannelHub`.

- [ ] **Step 3: Implement startup delegation**

Change `startup.py` so:
- it imports `ChannelHub`;
- `_maybe_start_feishu(app, settings, config_service)` returns `await ChannelHub(config_service=config_service).maybe_start_feishu(app, settings)`;
- lifespan passes the existing `config_service` into `_maybe_start_feishu`.

Keep shutdown behavior unchanged in this package. Direct adapter stop at shutdown remains a transition detail until channel runtime shutdown is migrated.

- [ ] **Step 4: Run startup test to verify GREEN**

Run: `pytest tests/test_startup.py::test_startup_maybe_start_feishu_delegates_to_channel_hub -q`

Expected: PASS.

### Task 3: Update Architecture Notes And Verify

**Files:**
- Modify: `docs/phase3/panel-control-plane-boundary.md`
- Modify: `docs/phase3/phase-3-closure-status.md`

- [ ] **Step 1: Update docs**

Record that startup Feishu auto-start now delegates to `ChannelHub`. Leave FeishuAdapter standard `ChannelMessage` processing as the next ChannelHub migration package.

- [ ] **Step 2: Run focused tests**

Run:

```bash
pytest tests/test_channel_hub.py tests/test_startup.py -q
pytest tests/test_startup.py tests/test_channel_hub.py tests/test_feishu_channel.py tests/test_feishu_path.py -q
```

Expected: PASS.

- [ ] **Step 3: Run panel and architecture regressions**

Run:

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py -q
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

Expected: full pytest passes; diff check passes; status shows only intended files before commit.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/plans/2026-05-27-phase-4-startup-feishu-channel-hub.md docs/phase3/panel-control-plane-boundary.md docs/phase3/phase-3-closure-status.md src/agentmind/channels/hub.py src/agentmind/startup.py tests/test_channel_hub.py tests/test_startup.py
git commit -m "refactor: route startup feishu through channel hub"
```
