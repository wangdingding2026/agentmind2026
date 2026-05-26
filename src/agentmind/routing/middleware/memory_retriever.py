import re

from agentmind.memory.service import MemoryService


class MemoryRetriever:

    async def retrieve(self, message: str, user_id: str, limit: int = 5) -> list[dict]:
        if not user_id:
            return []

        svc = MemoryService()

        followup = await _retrieve_result_set_followup(svc, message, user_id, limit)
        if followup is not None:
            return followup

        # v4 检索开关
        if _use_v4_retrieval():
            try:
                result = await svc.retrieve(message, user_id)
                items = result.get("recall_items", [])
                # 兼容旧格式：将 assembled_context 注入到结果中
                if result.get("assembled_context"):
                    items.insert(0, {"_v4_assembled": True, "_assembled_context": result["assembled_context"]})
                return items[:limit * 3]
            except Exception:
                pass  # 失败回退旧路径

        # 尝试从消息中提取日期（如 5月22日、5-22、2026-05-22）
        date_filter = _extract_date(message)

        recent = await svc.search_memory(
            query="", user_id=user_id, access_levels=["shared"], limit=10,
        )

        keyword = []
        if len(message.strip()) > 3:
            keyword = await svc.search_memory(
                query=message, user_id=user_id, access_levels=["shared"], limit=20,
            )

        seen = {m["memory_id"] for m in recent}
        merged = list(recent)
        for m in keyword:
            if m["memory_id"] not in seen and len(merged) < 20:
                seen.add(m["memory_id"])
                merged.append(m)

        # 如果提取到了日期，显式查询该日期的记忆（FTS5 中文检索不精准的补偿）
        if date_filter:
            date_entries = await svc.search_memory(
                query="", user_id=user_id, access_levels=["shared"], limit=100,
            )
            date_matches = [
                m for m in date_entries
                if (m.get("created_at") or "")[:10] == date_filter
                and m["memory_id"] not in seen
            ]
            for m in date_matches:
                seen.add(m["memory_id"])
                merged.insert(0, m)  # 插到最前面

        return merged[:limit * 3]


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


def _use_v4_retrieval() -> bool:
    try:
        import yaml
        from agentmind.storage.db import CONFIG_DIR
        path = CONFIG_DIR / "settings.yaml"
        if not path.exists():
            return False
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return bool(data.get("memory", {}).get("v4_retrieval_enabled", False))
    except Exception:
        return False


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
