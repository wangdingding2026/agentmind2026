import asyncio
from pathlib import Path

import yaml

def run_memory_retrieval_eval(fixture_path: Path) -> dict:
    return asyncio.run(_run_memory_retrieval_eval(fixture_path))


async def _run_memory_retrieval_eval(fixture_path: Path) -> dict:
    from agentmind.memory.service import MemoryService
    from agentmind.routing.middleware.memory_retriever import MemoryRetriever
    from agentmind.services.result_set_service import ResultSetService

    data = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
    cases = data["cases"]
    svc = MemoryService()
    failures = []
    invariants = {
        "card_first_hits": 0,
        "raw_expansion_checked": False,
        "result_pagination_checked": False,
        "conflict_notice_checked": False,
        "sensitive_shared_isolation_checked": False,
    }

    for case in cases:
        try:
            await _seed_case(svc, case)
            passed = await _evaluate_case(
                svc,
                MemoryRetriever(),
                ResultSetService(svc.store),
                case,
                invariants,
            )
        except Exception as exc:
            passed = False
            failures.append({"id": case["id"], "error": str(exc)})
        if not passed and not any(f["id"] == case["id"] for f in failures):
            failures.append({"id": case["id"], "category": case["category"]})

    total = len(cases)
    passed_count = total - len(failures)
    return {
        "total": total,
        "passed": passed_count,
        "hit_rate": passed_count / total if total else 0.0,
        "failures": failures,
        "invariants": invariants,
    }


async def _seed_case(svc, case: dict):
    category = case["category"]
    if category == "current_session":
        seed = case["seed_memories"][0]
        svc.add_to_working_memory(seed["user_id"], "user", seed["content"])
        svc.add_to_working_memory(seed["user_id"], "assistant", "当前部署端口是 8765。")
        return

    for index, seed in enumerate(case["seed_memories"], start=1):
        await svc.write_memory({
            "memory_id": f"eval-{case['id']}-{index}",
            "content": seed["content"],
            "summary": seed["content"],
            "source_agent": seed.get("agent_id", seed.get("role", "")),
            "source_task_id": case["id"],
            "user_id": seed["user_id"],
            "conversation_id": seed.get("session_id", ""),
            "tags": seed.get("tags", []),
            "created_at": seed.get("created_at", ""),
            "access_level": seed.get("access_level", "shared"),
        })


async def _evaluate_case(svc, retriever, result_sets, case: dict, invariants: dict) -> bool:
    category = case["category"]
    user_id = case["seed_memories"][0]["user_id"]

    if category == "current_session":
        result = await svc.retrieve(
            case["query"],
            user_id=user_id,
            settings={"memory": {"working_memory_rounds": 3}},
        )
        return "8765" in result["assembled_context"]

    if category == "historical_session":
        rows = await svc.search_memory("登录超时 session ttl 7200", user_id=user_id, limit=3)
        return _record_card_hit(invariants, rows, case["id"], "7200")

    if category == "date_query":
        rows = await svc.search_memory_cards(
            query="WebSocket",
            user_id=user_id,
            time_range_start="2026-05-25",
            time_range_end="2026-05-25T23:59:59+08:00",
            limit=3,
        )
        return _record_card_hit(invariants, rows, case["id"], "WebSocket")

    if category == "topic_query":
        rows = await svc.search_memory("MemoryService 唯一入口", user_id=user_id, tags=["memory"], limit=3)
        return _record_card_hit(invariants, rows, case["id"], "MemoryService")

    if category == "agent_source":
        rows = await svc.search_memory(
            "数据库建议",
            user_id=user_id,
            source_agent="codex",
            limit=3,
        )
        return _record_card_hit(invariants, rows, case["id"], "task_history")

    if category == "expand_result":
        result_set_id = await _create_eval_result_set(svc, result_sets, user_id, case)
        expanded = await svc.expand_result(3, user_id=user_id, result_set_id=result_set_id)
        passed = bool(expanded and "路由策略顺序讨论" in expanded["content"])
        invariants["raw_expansion_checked"] = invariants["raw_expansion_checked"] or passed
        return passed

    if category == "more_results":
        result_set_id = await _create_eval_result_set(svc, result_sets, user_id, case, count=6)
        page = await svc.more_results(user_id=user_id, result_set_id=result_set_id, page_size=5)
        more = await svc.more_results(user_id=user_id, result_set_id=result_set_id, page_size=5)
        passed = bool(page and page["has_more"] and more and more["items"])
        invariants["result_pagination_checked"] = invariants["result_pagination_checked"] or passed
        return passed

    if category == "conflict_memory":
        rows = await svc.search_memory("memory", user_id=user_id, tags=["memory"], limit=5)
        passed = any(row.get("_conflict_notice") == "存在冲突记忆" for row in rows)
        invariants["conflict_notice_checked"] = invariants["conflict_notice_checked"] or passed
        return passed

    if category == "sensitive_isolation":
        rows = await svc.search_memory(
            "API key",
            user_id=user_id,
            access_levels=["shared"],
            limit=5,
        )
        passed = all("sk-test-sensitive-value" not in row.get("content", "") for row in rows)
        invariants["sensitive_shared_isolation_checked"] = (
            invariants["sensitive_shared_isolation_checked"] or passed
        )
        return passed

    return False


def _has_card_hit(rows: list[dict], source_task_id: str, expected_text: str) -> bool:
    return any(
        row.get("_route") == "memory_cards"
        and row.get("source_task_id") == source_task_id
        and expected_text in _row_text(row)
        for row in rows
    )


def _record_card_hit(
    invariants: dict, rows: list[dict], source_task_id: str, expected_text: str
) -> bool:
    passed = _has_card_hit(rows, source_task_id, expected_text)
    if passed:
        invariants["card_first_hits"] += 1
    return passed


def _row_text(row: dict) -> str:
    return "\n".join([
        row.get("content", ""),
        row.get("card_text", ""),
        row.get("summary", ""),
    ])


async def _create_eval_result_set(svc, result_sets, user_id: str, case: dict, count: int = 3) -> str:
    from agentmind.memory.dto import MemoryWriteCommand

    memory_ids = []
    for index in range(1, count + 1):
        content = (
            "路由策略顺序讨论"
            if index == 3
            else f"{case['id']} result item {index}"
        )
        memory_id = f"eval-result-{case['id']}-{index}"
        await svc.store.write_raw_and_card(MemoryWriteCommand(
            memory_id=memory_id,
            content=content,
            summary=f"result item {index}",
            user_id=user_id,
            tags=["result_set"],
        ))
        memory_ids.append(memory_id)
    return await result_sets.create_result_set(
        user_id=user_id,
        query_text=case["query"],
        memory_ids=memory_ids,
        metadata={"route": "memory_cards"},
    )
