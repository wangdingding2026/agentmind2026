from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable


@dataclass(slots=True)
class ChannelMessage:
    channel_id: str
    sender_id: str
    text: str
    raw_payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChannelStatus:
    channel_id: str
    channel_type: str
    enabled: bool = False
    connected: bool = False
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChannelHub:
    def __init__(
        self,
        message_handler: Callable[[ChannelMessage], Awaitable[Any]] | None = None,
    ):
        self._channels: dict[str, Any] = {}
        self._statuses: dict[str, ChannelStatus] = {}
        self._message_handler = message_handler

    def register_channel(self, channel_id: str, adapter: Any, channel_type: str):
        self._channels[channel_id] = adapter
        self._statuses[channel_id] = ChannelStatus(
            channel_id=channel_id,
            channel_type=channel_type,
        )

    async def start_channel(self, channel_id: str) -> dict[str, Any]:
        adapter = self._channels.get(channel_id)
        if adapter is None:
            return self._unknown_channel_result(channel_id)

        status = self._statuses[channel_id]
        try:
            await adapter.start()
        except Exception as exc:
            status.enabled = False
            status.connected = False
            status.last_error = str(exc)
            return {"ok": False, "channel_id": channel_id, "error": str(exc)}

        status.enabled = True
        status.connected = True
        status.last_error = ""
        return {"ok": True, "channel_id": channel_id}

    async def stop_channel(self, channel_id: str) -> dict[str, Any]:
        adapter = self._channels.get(channel_id)
        if adapter is None:
            return self._unknown_channel_result(channel_id)

        status = self._statuses[channel_id]
        try:
            await adapter.stop()
        except Exception as exc:
            status.last_error = str(exc)
            return {"ok": False, "channel_id": channel_id, "error": str(exc)}

        status.enabled = False
        status.connected = False
        status.last_error = ""
        return {"ok": True, "channel_id": channel_id}

    def channel_status(self, channel_id: str) -> dict[str, Any] | None:
        status = self._statuses.get(channel_id)
        return status.to_dict() if status else None

    def list_statuses(self) -> list[dict[str, Any]]:
        return [status.to_dict() for status in self._statuses.values()]

    async def dispatch_message(self, message: ChannelMessage):
        if self._message_handler is None:
            return None
        return await self._message_handler(message)

    @staticmethod
    def _unknown_channel_result(channel_id: str) -> dict[str, Any]:
        return {
            "ok": False,
            "channel_id": channel_id,
            "error": "Channel not registered",
        }
