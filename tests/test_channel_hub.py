import pytest


class _Adapter:
    def __init__(self, fail_start=False, fail_stop=False):
        self.fail_start = fail_start
        self.fail_stop = fail_stop
        self.started = 0
        self.stopped = 0
        self.sent = []
        self._ws_thread = _Thread(True)

    async def start(self):
        self.started += 1
        if self.fail_start:
            raise RuntimeError("start failed")

    async def stop(self):
        self.stopped += 1
        if self.fail_stop:
            raise RuntimeError("stop failed")

    async def send_message(self, user_id, content):
        self.sent.append((user_id, content))


class _Thread:
    def __init__(self, alive):
        self._alive = alive

    def is_alive(self):
        return self._alive


class _State:
    pass


class _App:
    def __init__(self):
        self.state = _State()
        self.state.agent_registry = object()
        self.state.rule_engine = object()
        self.state.settings = {"feishu": {"enabled": False}}


class _ConfigService:
    def __init__(self):
        self.updated = []
        self.written = []
        self.settings = {"feishu": {"enabled": True, "app_id": "app", "app_secret": "secret"}}

    def update_settings_sections(self, sections):
        self.updated.append(sections)

    def read_settings(self):
        return self.settings

    def write_settings(self, data):
        self.written.append(data)
        self.settings = data


def test_channel_message_defaults():
    from agentmind.channels.hub import ChannelMessage

    message = ChannelMessage(channel_id="feishu", sender_id="u1", text="hello")

    assert message.channel_id == "feishu"
    assert message.sender_id == "u1"
    assert message.text == "hello"
    assert message.raw_payload == {}
    assert message.metadata == {}


def test_channel_hub_registers_channel_with_initial_status():
    from agentmind.channels.hub import ChannelHub

    hub = ChannelHub()
    hub.register_channel("feishu", _Adapter(), channel_type="feishu")

    assert hub.channel_status("feishu") == {
        "channel_id": "feishu",
        "channel_type": "feishu",
        "enabled": False,
        "connected": False,
        "last_error": "",
    }
    assert hub.list_statuses() == [hub.channel_status("feishu")]


@pytest.mark.asyncio
async def test_channel_hub_starts_and_stops_registered_channel():
    from agentmind.channels.hub import ChannelHub

    adapter = _Adapter()
    hub = ChannelHub()
    hub.register_channel("feishu", adapter, channel_type="feishu")

    assert await hub.start_channel("feishu") == {"ok": True, "channel_id": "feishu"}
    assert adapter.started == 1
    assert hub.channel_status("feishu")["enabled"] is True
    assert hub.channel_status("feishu")["connected"] is True

    assert await hub.stop_channel("feishu") == {"ok": True, "channel_id": "feishu"}
    assert adapter.stopped == 1
    assert hub.channel_status("feishu")["enabled"] is False
    assert hub.channel_status("feishu")["connected"] is False


@pytest.mark.asyncio
async def test_channel_hub_records_lifecycle_errors():
    from agentmind.channels.hub import ChannelHub

    hub = ChannelHub()
    hub.register_channel("feishu", _Adapter(fail_start=True), channel_type="feishu")

    result = await hub.start_channel("feishu")

    assert result == {"ok": False, "channel_id": "feishu", "error": "start failed"}
    assert hub.channel_status("feishu")["connected"] is False
    assert hub.channel_status("feishu")["last_error"] == "start failed"


@pytest.mark.asyncio
async def test_channel_hub_dispatches_standard_message_to_handler():
    from agentmind.channels.hub import ChannelHub, ChannelMessage

    received = []

    async def handler(message):
        received.append(message)
        return "ok"

    hub = ChannelHub(message_handler=handler)
    message = ChannelMessage(channel_id="feishu", sender_id="u1", text="hello")

    assert await hub.dispatch_message(message) == "ok"
    assert received == [message]


@pytest.mark.asyncio
async def test_channel_hub_rejects_unknown_channel_lifecycle_calls():
    from agentmind.channels.hub import ChannelHub

    hub = ChannelHub()

    assert await hub.start_channel("missing") == {
        "ok": False,
        "channel_id": "missing",
        "error": "Channel not registered",
    }
    assert hub.channel_status("missing") is None


@pytest.mark.asyncio
async def test_channel_hub_connects_feishu_with_existing_response_shape():
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

    result = await hub.connect_feishu(app, "app", "secret")

    assert result == {"ok": True, "connected": True}
    assert config_service.updated == [{
        "feishu": {"enabled": True, "app_id": "app", "app_secret": "secret"}
    }]
    assert app.state.settings["feishu"] == {"enabled": True, "app_id": "app", "app_secret": "secret"}
    assert app.state.feishu_adapter.started == 1
    assert created[0]["app_id"] == "app"
    assert created[0]["app_secret"] == "secret"


@pytest.mark.asyncio
async def test_channel_hub_disconnects_feishu_and_disables_config():
    from agentmind.channels.hub import ChannelHub

    app = _App()
    adapter = _Adapter()
    app.state.feishu_adapter = adapter
    config_service = _ConfigService()
    hub = ChannelHub(config_service=config_service)

    result = await hub.disconnect_feishu(app)

    assert result == {"ok": True}
    assert adapter.stopped == 1
    assert app.state.feishu_adapter is None
    assert config_service.settings["feishu"]["enabled"] is False
    assert config_service.written == [config_service.settings]


def test_channel_hub_reports_feishu_status():
    from agentmind.channels.hub import ChannelHub

    app = _App()
    app.state.feishu_adapter = _Adapter()

    assert ChannelHub().feishu_status(app) == {"enabled": True, "connected": True}


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


@pytest.mark.asyncio
async def test_channel_hub_feishu_callback_provides_send_func_to_routing():
    from agentmind.channels.hub import ChannelHub

    app = _App()
    adapter = _Adapter()
    captured = {}

    def adapter_factory(**kwargs):
        captured["callback"] = kwargs["route_callback"]
        return adapter

    async def route_stream_func(*args, **kwargs):
        await kwargs["send_func"]("side effect reply")
        yield "ok"

    hub = ChannelHub(
        config_service=_ConfigService(),
        feishu_adapter_factory=adapter_factory,
        route_stream_func=route_stream_func,
    )
    await hub.connect_feishu(app, "app", "secret")

    chunks = []
    async for chunk in captured["callback"]("hello", "u1"):
        chunks.append(chunk)

    assert chunks == ["ok"]
    assert adapter.sent == [("u1", "side effect reply")]


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
