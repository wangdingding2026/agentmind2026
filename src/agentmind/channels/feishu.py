"""飞书通道适配器 — WebSocket 长连接"""

import asyncio
import json
import logging
import re
import threading
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from .base import ChannelAdapter

logger = logging.getLogger("agentmind.channel.feishu")
_LARK_MODULES: dict[str, object] | None = None


def _load_lark_modules() -> dict[str, object]:
    """Load Feishu SDK only when a real Feishu operation needs it."""
    global _LARK_MODULES
    if _LARK_MODULES is not None:
        return _LARK_MODULES

    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateMessageReactionRequest, CreateMessageReactionRequestBody,
        CreateMessageRequest, CreateMessageRequestBody,
        DeleteMessageReactionRequest,
        Emoji,
        ReplyMessageRequest, ReplyMessageRequestBody,
    )
    from lark_oapi.event.dispatcher_handler import EventDispatcherHandler

    _LARK_MODULES = {
        "lark": lark,
        "CreateMessageReactionRequest": CreateMessageReactionRequest,
        "CreateMessageReactionRequestBody": CreateMessageReactionRequestBody,
        "CreateMessageRequest": CreateMessageRequest,
        "CreateMessageRequestBody": CreateMessageRequestBody,
        "DeleteMessageReactionRequest": DeleteMessageReactionRequest,
        "Emoji": Emoji,
        "ReplyMessageRequest": ReplyMessageRequest,
        "ReplyMessageRequestBody": ReplyMessageRequestBody,
        "EventDispatcherHandler": EventDispatcherHandler,
    }
    return _LARK_MODULES


class FeishuAdapter(ChannelAdapter):
    """飞书 WebSocket 长连接适配器。SDK 阻塞调用隔离在独立线程，通过 Queue 通信"""

    def __init__(self, app_id: str, app_secret: str, message_callback=None):
        self.app_id = app_id
        self.app_secret = app_secret
        self.message_callback = message_callback

        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._api_client = None
        self._ws_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._main_loop_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._processed_msgs: deque[str] = deque(maxlen=1000)

    def _get_api_client(self):
        if self._api_client is None:
            sdk = _load_lark_modules()
            lark = sdk["lark"]
            self._api_client = lark.Client.builder().app_id(self.app_id).app_secret(self.app_secret).build()
        return self._api_client

    async def start(self):
        if self._ws_thread and self._ws_thread.is_alive():
            logger.warning("飞书通道已在运行中")
            return

        self._loop = asyncio.get_running_loop()
        self._stop_event.clear()

        self._ws_thread = threading.Thread(target=self._run_ws_client, daemon=True)
        self._ws_thread.start()

        self._main_loop_task = asyncio.create_task(self._process_messages())
        logger.info("飞书通道适配器已启动")

    async def _add_reaction(self, msg_id: str, emoji_type: str = "MUSCLE") -> str:
        """给消息加表情，返回 reaction_id"""
        try:
            sdk = _load_lark_modules()
            CreateMessageReactionRequest = sdk["CreateMessageReactionRequest"]
            CreateMessageReactionRequestBody = sdk["CreateMessageReactionRequestBody"]
            Emoji = sdk["Emoji"]
            req = (
                CreateMessageReactionRequest.builder()
                .message_id(msg_id)
                .request_body(
                    CreateMessageReactionRequestBody.builder()
                    .reaction_type(Emoji.builder().emoji_type(emoji_type).build())
                    .build()
                )
                .build()
            )
            resp = await asyncio.to_thread(self._get_api_client().im.v1.message_reaction.create, req)
            logger.info("表情已添加: msg_id=%s reaction_id=%s", msg_id, resp.data.reaction_id if resp.data else "none")
            return resp.data.reaction_id if resp.data else ""
        except Exception as e:
            logger.warning("添加表情失败: %s", e)
            return ""

    async def _remove_reaction(self, msg_id: str, reaction_id: str):
        """移除消息表情"""
        if not reaction_id:
            return
        try:
            sdk = _load_lark_modules()
            DeleteMessageReactionRequest = sdk["DeleteMessageReactionRequest"]
            req = (
                DeleteMessageReactionRequest.builder()
                .message_id(msg_id)
                .reaction_id(reaction_id)
                .build()
            )
            await asyncio.to_thread(self._get_api_client().im.v1.message_reaction.delete, req)
            logger.info("表情已移除: msg_id=%s", msg_id)
        except Exception as e:
            logger.warning("移除表情失败: %s", e)

    async def send_message(self, user_id: str, content: str, root_msg_id: str = ""):
        MAX_LEN = 4000
        chunks = [content[i:i + MAX_LEN] for i in range(0, len(content), MAX_LEN)]
        for chunk in chunks:
            try:
                sdk = _load_lark_modules()
                if root_msg_id:
                    ReplyMessageRequest = sdk["ReplyMessageRequest"]
                    ReplyMessageRequestBody = sdk["ReplyMessageRequestBody"]
                    # 回复消息：显示在原消息下方
                    req = (
                        ReplyMessageRequest.builder()
                        .message_id(root_msg_id)
                        .request_body(
                            ReplyMessageRequestBody.builder()
                            .content(json.dumps({"text": chunk}))
                            .msg_type("text")
                            .build()
                        )
                        .build()
                    )
                    await asyncio.to_thread(self._get_api_client().im.v1.message.reply, req)
                else:
                    CreateMessageRequest = sdk["CreateMessageRequest"]
                    CreateMessageRequestBody = sdk["CreateMessageRequestBody"]
                    req = (
                        CreateMessageRequest.builder()
                        .receive_id_type("open_id")
                        .request_body(
                            CreateMessageRequestBody.builder()
                            .receive_id(user_id)
                            .msg_type("text")
                            .content(json.dumps({"text": chunk}))
                            .build()
                        )
                        .build()
                    )
                    await asyncio.to_thread(self._get_api_client().im.v1.message.create, req)
            except Exception as e:
                logger.error("飞书消息发送异常: %s", e)

    async def stop(self):
        logger.info("正在停止飞书通道...")
        self._stop_event.set()

        if self._main_loop_task and not self._main_loop_task.done():
            self._main_loop_task.cancel()
            try:
                await self._main_loop_task
            except asyncio.CancelledError:
                pass

        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=3.0)

        logger.info("飞书通道已关闭")

    # ========== 内部实现 ==========

    def _run_ws_client(self):
        # SDK 在模块加载时调了 asyncio.get_event_loop()，必须在独立线程中替换
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        sdk = _load_lark_modules()
        lark = sdk["lark"]
        EventDispatcherHandler = sdk["EventDispatcherHandler"]
        import lark_oapi.ws.client as _ws_client
        _ws_client.loop = loop

        handler = (
            EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message)
            .build()
        )
        client = lark.ws.Client(
            app_id=self.app_id,
            app_secret=self.app_secret,
            event_handler=handler,
        )
        try:
            client.start()
        except Exception as e:
            if not self._stop_event.is_set():
                logger.error("飞书 WebSocket 客户端异常退出: %s", e)
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()

    def _on_message(self, data: "P2ImMessageReceiveV1"):
        try:
            event = data.event
            msg_id = event.message.message_id
            chat_type = str(getattr(event.message, 'chat_type', ''))
            logger.info("收到飞书消息: msg_id=%s chat_type=%s", msg_id, chat_type)
            if msg_id in self._processed_msgs:
                logger.info("消息重复，已忽略: %s", msg_id)
                return
            self._processed_msgs.append(msg_id)

            text = self._extract_text(event.message.content)
            logger.info("消息清洗: %s", (text or '(空)')[:80])
            if not text:
                logger.warning("消息被丢弃（清洗后为空），原始内容: %s", str(event.message.content)[:200])
                return

            sender_id = event.sender.sender_id.open_id
            try:
                self._loop.call_soon_threadsafe(
                    self._message_queue.put_nowait,
                    {"sender_id": sender_id, "text": text, "msg_id": msg_id},
                )
            except Exception as e:
                logger.error("消息入队失败: %s", e)
        except Exception as e:
            logger.error("飞书消息解析失败: %s", e)

    def _extract_text(self, raw_content: str) -> str:
        """提取消息文本，剥离 at 标签保留用户名"""
        try:
            content_dict = json.loads(raw_content)
            text = content_dict.get("text", "")
            cleaned = re.sub(r'<at[^>]+>(@?[^<]*)</at>', r'\1', text)
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            return cleaned
        except Exception:
            return ""

    def _to_channel_message(self, msg: dict):
        from agentmind.channels.hub import ChannelMessage

        return ChannelMessage(
            channel_id="feishu",
            sender_id=str(msg.get("sender_id", "")),
            text=str(msg.get("text", "")),
            raw_payload=dict(msg),
            metadata={"msg_id": str(msg.get("msg_id", ""))},
        )

    async def _process_messages(self):
        logger.info("消息处理循环已启动")
        while True:
            try:
                try:
                    msg = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                logger.info("队列取出消息: sender=%s", msg.get("sender_id"))

                try:
                    msg_text = str(msg.get("text", "")).strip().lower()
                    logger.info("开始处理飞书消息: sender=%s text=%s", msg["sender_id"], msg_text[:50])
                    root_id = msg.get("msg_id", "")
                    reaction_id = ""
                    # 加表情表示处理中
                    reaction_id = await self._add_reaction(root_id)
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
                    # 移除表情
                    await self._remove_reaction(root_id, reaction_id)
                    final = "".join(full_output)
                    logger.info("路由完成: sender=%s len=%d", msg["sender_id"], len(final))
                    if final:
                        await self.send_message(msg["sender_id"], final, root_id)
                    else:
                        await self.send_message(msg["sender_id"], "Agent 执行完成但未返回结果，请检查 Agent 配置或重试", root_id)
                except Exception as e:
                    logger.error("路由处理失败: %s", e)
                    await self._remove_reaction(root_id, reaction_id)
                    await self.send_message(msg["sender_id"], f"处理请求时出错：{str(e)[:100]}", root_id)
            except asyncio.CancelledError:
                logger.info("飞书消息处理循环已取消")
                break
