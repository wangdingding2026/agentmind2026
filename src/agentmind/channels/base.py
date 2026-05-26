"""消息通道适配器抽象基类"""

from abc import ABC, abstractmethod


class ChannelAdapter(ABC):
    """消息通道适配器基类。所有消息平台（飞书、终端等）实现此接口"""

    @abstractmethod
    async def start(self):
        """启动通道，开始监听消息（非阻塞）"""
        ...

    @abstractmethod
    async def send_message(self, user_id: str, content: str):
        """向指定用户发送消息"""
        ...

    @abstractmethod
    async def stop(self):
        """关闭通道连接，清理资源"""
        ...
