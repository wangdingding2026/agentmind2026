import pytest


@pytest.mark.asyncio
async def test_memory_conflict_detector_marks_conflicting_memory_cards():
    from agentmind.memory.service import MemoryService

    svc = MemoryService()
    await svc.write_memory({
        "memory_id": "conflict-card-old",
        "content": "建议继续直接检索 memory_entries。",
        "summary": "继续检索 memory_entries",
        "source_agent": "agent_a",
        "source_task_id": "task-old",
        "user_id": "u_conflict",
        "tags": ["memory", "architecture"],
    })
    await svc.write_memory({
        "memory_id": "conflict-card-new",
        "content": "建议新增 memory_cards，检索只搜卡片，原文按 raw_id 回查。",
        "summary": "检索只搜 memory_cards",
        "source_agent": "agent_b",
        "source_task_id": "task-new",
        "user_id": "u_conflict",
        "tags": ["memory", "architecture"],
    })

    old_card = await svc.store.get_card("conflict-card-old")
    new_card = await svc.store.get_card("conflict-card-new")

    old_conflicts = old_card["score_metadata"].get("conflicts", [])
    new_conflicts = new_card["score_metadata"].get("conflicts", [])

    assert old_conflicts
    assert new_conflicts
    assert old_conflicts[0]["memory_id"] == "conflict-card-new"
    assert new_conflicts[0]["memory_id"] == "conflict-card-old"
    assert old_conflicts[0]["reason"] == "opposing_memory_architecture_recommendation"


@pytest.mark.asyncio
async def test_memory_service_search_surfaces_card_conflict_hints():
    from agentmind.memory.service import MemoryService

    svc = MemoryService()
    await svc.write_memory({
        "memory_id": "search-conflict-old",
        "content": "建议继续直接检索 memory_entries。",
        "summary": "继续检索 memory_entries",
        "source_agent": "agent_a",
        "source_task_id": "task-old",
        "user_id": "u_conflict_search",
        "tags": ["memory", "architecture"],
    })
    await svc.write_memory({
        "memory_id": "search-conflict-new",
        "content": "建议新增 memory_cards，检索只搜卡片，原文按 raw_id 回查。",
        "summary": "检索只搜 memory_cards",
        "source_agent": "agent_b",
        "source_task_id": "task-new",
        "user_id": "u_conflict_search",
        "tags": ["memory", "architecture"],
    })

    rows = await svc.search_memory(
        query="memory",
        user_id="u_conflict_search",
        tags=["memory"],
        limit=5,
    )

    conflicted = [row for row in rows if row["memory_id"] == "search-conflict-new"][0]

    assert conflicted["_conflicts"]
    assert conflicted["_conflicts"][0]["memory_id"] == "search-conflict-old"
    assert conflicted["_conflict_notice"] == "存在冲突记忆"
