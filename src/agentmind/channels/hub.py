from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable

from agentmind.storage.db import CONFIG_DIR


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
        config_service: Any | None = None,
        feishu_adapter_factory: Callable[..., Any] | None = None,
        route_stream_func: Callable[..., Any] | None = None,
        channel_replay_service: Any | None = None,
    ):
        self._channels: dict[str, Any] = {}
        self._statuses: dict[str, ChannelStatus] = {}
        self._message_handler = message_handler
        self._config_service = config_service
        self._feishu_adapter_factory = feishu_adapter_factory
        self._route_stream_func = route_stream_func
        self._channel_replay_service = channel_replay_service

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

    async def _handle_feishu_message(self, app: Any, message: ChannelMessage) -> list[str]:
        replay_result = await self._handle_channel_replay(message)
        if replay_result is not None:
            return [replay_result]

        stop_result = self._handle_feishu_discussion_stop(message)
        if stop_result is not None:
            return stop_result

        route_stream_func = self._route_stream_func or self._default_route_stream_func

        async def _send(text: str):
            adapter = getattr(app.state, "feishu_adapter", None)
            if adapter:
                await adapter.send_message(message.sender_id, text)

        chunks = []
        strategy_manager = getattr(app.state, "strategy_manager", None)
        async for chunk in route_stream_func(
            message.text,
            message.sender_id,
            app.state.agent_registry,
            app.state.rule_engine,
            app.state.settings,
            send_func=_send,
            strategy_manager=strategy_manager,
        ):
            chunks.append(chunk)
        return chunks

    async def _handle_channel_replay(self, message: ChannelMessage) -> str | None:
        service = self._channel_replay_service
        if service is None:
            from agentmind.services.channel_replay_service import ChannelReplayService

            service = ChannelReplayService()
            self._channel_replay_service = service
        return await service.handle_text(message.text)

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

    async def connect_feishu(self, app: Any, app_id: str, app_secret: str) -> dict[str, Any]:
        app_id = app_id.strip()
        app_secret = app_secret.strip()
        if not app_id or not app_secret:
            return {"ok": False, "error": "App ID 和 App Secret 不能为空"}

        feishu_config = {"enabled": True, "app_id": app_id, "app_secret": app_secret}
        self._get_config_service().update_settings_sections({"feishu": feishu_config})

        old_adapter = getattr(app.state, "feishu_adapter", None)
        if old_adapter:
            await old_adapter.stop()

        app.state.settings["feishu"] = feishu_config

        try:
            adapter = self._create_feishu_adapter(app, app_id, app_secret)
            await adapter.start()
            if self._is_adapter_connected(adapter):
                app.state.feishu_adapter = adapter
                return {"ok": True, "connected": True}

            await adapter.stop()
            return {
                "ok": False,
                "error": "WebSocket 连接失败，请检查 app_id/app_secret 是否正确，或查看服务日志",
            }
        except Exception as exc:
            return {"ok": False, "error": f"连接失败: {exc}"}

    async def disconnect_feishu(self, app: Any) -> dict[str, bool]:
        adapter = getattr(app.state, "feishu_adapter", None)
        if adapter:
            await adapter.stop()
            app.state.feishu_adapter = None

        service = self._get_config_service()
        data = service.read_settings()
        if isinstance(data, dict) and "feishu" in data:
            data["feishu"]["enabled"] = False
            service.write_settings(data)
        return {"ok": True}

    def feishu_status(self, app: Any) -> dict[str, bool]:
        adapter = getattr(app.state, "feishu_adapter", None)
        return {
            "enabled": adapter is not None,
            "connected": self._is_adapter_connected(adapter),
        }

    async def maybe_start_feishu(self, app: Any, settings: dict[str, Any]):
        feishu_cfg = settings.get("feishu", {}) if isinstance(settings, dict) else {}
        if not (
            feishu_cfg.get("enabled")
            and feishu_cfg.get("app_id")
            and feishu_cfg.get("app_secret")
        ):
            return None

        result = await self.connect_feishu(
            app,
            str(feishu_cfg["app_id"]),
            str(feishu_cfg["app_secret"]),
        )
        if result.get("ok"):
            return getattr(app.state, "feishu_adapter", None)
        return None

    @staticmethod
    def _unknown_channel_result(channel_id: str) -> dict[str, Any]:
        return {
            "ok": False,
            "channel_id": channel_id,
            "error": "Channel not registered",
        }

    def _get_config_service(self):
        if self._config_service is not None:
            return self._config_service

        from agentmind.services.config_service import ConfigService

        self._config_service = ConfigService(CONFIG_DIR)
        return self._config_service

    def _create_feishu_adapter(self, app: Any, app_id: str, app_secret: str):
        adapter_factory = self._feishu_adapter_factory or self._default_feishu_adapter_factory

        async def feishu_message_callback(message: ChannelMessage):
            return await self._handle_feishu_message(app, message)

        return adapter_factory(
            app_id=app_id,
            app_secret=app_secret,
            message_callback=feishu_message_callback,
        )

    @staticmethod
    def _is_adapter_connected(adapter: Any) -> bool:
        if adapter is None:
            return False
        thread = getattr(adapter, "_ws_thread", None)
        return bool(thread is not None and thread.is_alive())

    @staticmethod
    def _default_feishu_adapter_factory(**kwargs):
        from agentmind.channels.feishu import FeishuAdapter

        return FeishuAdapter(**kwargs)

    @staticmethod
    def _default_route_stream_func(*args, **kwargs):
        from agentmind.api.router import route_stream

        return route_stream(*args, **kwargs)
