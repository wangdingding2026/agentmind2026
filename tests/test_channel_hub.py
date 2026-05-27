import pytest


class _Adapter:
    def __init__(self, fail_start=False, fail_stop=False):
        self.fail_start = fail_start
        self.fail_stop = fail_stop
        self.started = 0
        self.stopped = 0
        self.sent = []

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
