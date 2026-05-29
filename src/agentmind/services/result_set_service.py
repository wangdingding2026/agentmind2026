"""ResultSetService — persisted memory card result navigation."""


class ResultSetService:
    """Persist ordered card search results and expand them through raw memory."""

    def __init__(self, store=None, repository=None):
        if repository is None:
            from agentmind.memory.repository_sqlite import SqliteMemoryRepository

            repository = SqliteMemoryRepository(getattr(store, "_db_path", ""))
        self._repository = repository

    async def create_result_set(
        self,
        user_id: str,
        query_text: str,
        memory_ids: list[str],
        metadata: dict | None = None,
    ) -> str:
        return await self._repository.create_result_set(
            user_id,
            query_text,
            [{"memory_id": memory_id} for memory_id in memory_ids],
            metadata or {},
        )

    async def expand_result(
        self, result_set_id: str, result_index: int, user_id: str = ""
    ) -> dict | None:
        return await self._repository.expand_result(result_set_id, result_index, user_id)

    async def next_page(
        self, result_set_id: str, user_id: str = "", page_size: int = 5
    ) -> dict | None:
        return await self._repository.next_page(result_set_id, user_id, page_size)

    async def get_latest_result_set_id(self, user_id: str) -> str | None:
        return await self._repository.get_latest_result_set_id(user_id)
