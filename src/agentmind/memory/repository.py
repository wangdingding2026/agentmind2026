"""Canonical memory repository abstraction."""

from abc import ABC, abstractmethod

from agentmind.memory.dto import MemoryWriteCommand


class IMemoryRepository(ABC):
    """Unified memory repository boundary."""

    @abstractmethod
    async def write_raw_and_card(self, command: MemoryWriteCommand) -> dict:
        ...

    @abstractmethod
    async def search_cards(
        self,
        *,
        query: str,
        user_id: str = "",
        tags: list[str] | None = None,
        source_agent: str = "",
        access_levels: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict]:
        ...

    @abstractmethod
    async def get_raw(self, raw_memory_id: str, user_id: str = "") -> dict | None:
        ...
