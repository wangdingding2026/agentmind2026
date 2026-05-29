import re

from agentmind.memory.dto import MemoryContext
from agentmind.memory.service import MemoryService


class MemoryRetriever:

    async def retrieve(
        self, message: str, user_id: str, limit: int = 5
    ) -> MemoryContext | list[dict]:
        if not user_id:
            return []

        svc = MemoryService()

        followup = await _retrieve_result_set_followup(svc, message, user_id, limit)
        if followup is not None:
            return followup

        return await svc.retrieve_context(message, user_id=user_id, limit=limit)


async def _retrieve_result_set_followup(
    svc: MemoryService, message: str, user_id: str, limit: int
) -> list[dict] | None:
    expand_index = _extract_expand_index(message)
    if expand_index is not None:
        expanded = await svc.expand_result(expand_index, user_id=user_id)
        return [expanded] if expanded else []

    if _is_more_results_query(message):
        page = await svc.more_results(user_id=user_id, page_size=limit)
        if not page:
            return []
        items = page.get("items", [])
        for item in items:
            item["_route"] = page.get("_route", "result_set_more")
        return items

    return None


def _extract_expand_index(message: str) -> int | None:
    match = re.search(r"展开\s*第\s*(\d+)\s*(条|个)?", message)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _is_more_results_query(message: str) -> bool:
    return bool(re.search(r"还有(别的|其他)?吗|还有别的吗|更多", message))


def _extract_date(message: str) -> str | None:
    """从中文消息中提取日期，返回 YYYY-MM-DD 格式"""
    # 5月22日、5月22
    m = re.search(r'(\d{1,2})\s*月\s*(\d{1,2})\s*日?', message)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            from datetime import datetime
            year = datetime.now().year
            return f"{year}-{month:02d}-{day:02d}"
    # 2026-05-22, 2026/05/22
    m = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', message)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year}-{month:02d}-{day:02d}"
    return None
