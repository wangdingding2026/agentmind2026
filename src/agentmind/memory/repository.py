"""记忆存储抽象接口 — 为未来切换存储底座留口子"""

from abc import ABC, abstractmethod

from agentmind.memory.types import MemoryEntry, SearchQuery, SearchResult


class IMemoryStore(ABC):
    """记忆存储抽象接口。当前实现为 SqliteMemoryStore。"""

    @abstractmethod
    async def insert(self, entry: MemoryEntry) -> str:
        """插入一条记忆，返回 memory_id"""
        ...

    @abstractmethod
    async def update(self, entry: MemoryEntry) -> str:
        """更新一条记忆，返回 memory_id"""
        ...

    @abstractmethod
    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """检索记忆，返回排序后的结果列表"""
        ...

    @abstractmethod
    async def delete(self, memory_id: str) -> bool:
        """删除一条记忆，返回是否成功"""
        ...

    @abstractmethod
    async def get(self, memory_id: str) -> MemoryEntry | None:
        """获取单条记忆"""
        ...

    @abstractmethod
    async def count(self, user_id: str = "") -> int:
        """计数"""
        ...

    @abstractmethod
    async def get_stats(self) -> dict:
        """获取统计信息"""
        ...

    @abstractmethod
    async def batch_insert(self, entries: list[MemoryEntry]) -> list[str]:
        """批量插入，返回 memory_id 列表"""
        ...
