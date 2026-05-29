import gzip
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest


def _seed_archive_row(
    data_dir,
    table_name: str,
    memory_id: str,
    user_id: str,
    content: str,
    summary: str = "",
    memory_type: str = "episodic",
    original_created_at: str = "2025-01-15 08:00:00",
):
    archive_path = data_dir / "archive.db"
    conn = sqlite3.connect(str(archive_path), timeout=10)
    try:
        conn.execute(
            f"""CREATE TABLE IF NOT EXISTS {table_name} (
                memory_id TEXT PRIMARY KEY,
                user_id TEXT,
                memory_type TEXT,
                content_compressed BLOB,
                summary TEXT,
                importance REAL,
                original_created_at TEXT,
                archived_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            f"""INSERT OR REPLACE INTO {table_name}
               (memory_id, user_id, memory_type, content_compressed, summary,
                importance, original_created_at, archived_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                memory_id,
                user_id,
                memory_type,
                gzip.compress(content.encode("utf-8")),
                summary,
                0.8,
                original_created_at,
                "2026-05-26 00:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_memory_service_searches_cold_archive_explicitly():
    from agentmind.memory.service import MemoryService
    from agentmind.storage.db import DATA_DIR

    _seed_archive_row(
        DATA_DIR,
        "archive_2025_01",
        "arch-1",
        "u_archive",
        "冷库原文包含长期项目决策：只通过 memory_cards 检索，raw/archive 回查原文。",
        summary="长期项目决策",
    )

    rows = await MemoryService().search_archive_memory(
        query="长期项目决策",
        user_id="u_archive",
        limit=5,
    )

    assert len(rows) == 1
    assert rows[0]["memory_id"] == "arch-1"
    assert rows[0]["content"].startswith("冷库原文包含长期项目决策")
    assert rows[0]["summary"] == "长期项目决策"
    assert rows[0]["_route"] == "archive"


@pytest.mark.asyncio
async def test_archive_search_matches_decompressed_content_when_summary_differs():
    from agentmind.memory.service import MemoryService
    from agentmind.storage.db import DATA_DIR

    _seed_archive_row(
        DATA_DIR,
        "archive_2025_06",
        "arch-content-only",
        "u_archive_content",
        "这条冷库原文只在正文里包含跨月归档回查关键词。",
        summary="普通摘要",
        original_created_at="2025-06-01 08:00:00",
    )

    rows = await MemoryService().search_archive_memory(
        query="跨月归档回查",
        user_id="u_archive_content",
        limit=5,
    )

    assert [row["memory_id"] for row in rows] == ["arch-content-only"]


@pytest.mark.asyncio
async def test_archive_search_is_user_scoped():
    from agentmind.memory.service import MemoryService
    from agentmind.storage.db import DATA_DIR

    _seed_archive_row(
        DATA_DIR,
        "archive_2025_02",
        "arch-user-a",
        "u_archive_a",
        "冷库用户隔离内容：属于 A 用户。",
        summary="冷库用户隔离",
        original_created_at="2025-02-01 08:00:00",
    )
    _seed_archive_row(
        DATA_DIR,
        "archive_2025_02",
        "arch-user-b",
        "u_archive_b",
        "冷库用户隔离内容：属于 B 用户，不能返回给 A。",
        summary="冷库用户隔离",
        original_created_at="2025-02-02 08:00:00",
    )

    rows = await MemoryService().search_archive_memory(
        query="冷库用户隔离",
        user_id="u_archive_a",
        limit=5,
    )

    assert [row["memory_id"] for row in rows] == ["arch-user-a"]


@pytest.mark.asyncio
async def test_archive_search_requires_user_scope():
    from agentmind.memory.service import MemoryService
    from agentmind.storage.db import DATA_DIR

    _seed_archive_row(
        DATA_DIR,
        "archive_2025_03",
        "arch-no-scope",
        "u_archive_private",
        "没有 user_id 时不能跨用户搜索这条冷库内容。",
        summary="跨用户冷库保护",
        original_created_at="2025-03-01 08:00:00",
    )

    rows = await MemoryService().search_archive_memory(
        query="跨用户冷库保护",
        limit=5,
    )

    assert rows == []


@pytest.mark.asyncio
async def test_result_expansion_falls_back_to_archive_when_raw_missing():
    from agentmind.memory.sqlite_store import SqliteMemoryStore
    from agentmind.memory.types import MemoryEntry
    from agentmind.services.result_set_service import ResultSetService
    from agentmind.storage.db import DATA_DIR

    store = SqliteMemoryStore()
    await store.insert(MemoryEntry(
        memory_id="arch-expand-1",
        content="hot raw content before archive",
        summary="archived expansion card",
        user_id="u_arch_expand",
        tags=["archive-expand"],
    ))
    conn = store._get_conn()
    try:
        conn.execute("DELETE FROM raw_memory WHERE memory_id=?", ("arch-expand-1",))
        conn.commit()
    finally:
        conn.close()
    _seed_archive_row(
        DATA_DIR,
        "archive_2025_04",
        "arch-expand-1",
        "u_arch_expand",
        "冷库回查展开原文：这是归档后的完整内容。",
        summary="archived expansion card",
        original_created_at="2025-04-01 08:00:00",
    )

    svc = ResultSetService(store)
    result_set_id = await svc.create_result_set(
        user_id="u_arch_expand",
        query_text="archived expansion",
        memory_ids=["arch-expand-1"],
        metadata={"route": "memory_cards"},
    )

    expanded = await svc.expand_result(result_set_id, 1, user_id="u_arch_expand")

    assert expanded["content"] == "冷库回查展开原文：这是归档后的完整内容。"
    assert expanded["raw_memory"]["_route"] == "archive"
    assert expanded["_raw_route"] == "archive"


@pytest.mark.asyncio
async def test_memory_service_expand_result_marks_archive_raw_route():
    from agentmind.memory.service import MemoryService
    from agentmind.memory.types import MemoryEntry
    from agentmind.services.result_set_service import ResultSetService
    from agentmind.storage.db import DATA_DIR

    svc = MemoryService()
    await svc.store.insert(MemoryEntry(
        memory_id="arch-expand-service-1",
        content="hot raw content before service archive",
        summary="service archived expansion card",
        user_id="u_arch_expand_service",
        tags=["archive-expand"],
    ))
    conn = svc.store._get_conn()
    try:
        conn.execute("DELETE FROM raw_memory WHERE memory_id=?", ("arch-expand-service-1",))
        conn.commit()
    finally:
        conn.close()
    _seed_archive_row(
        DATA_DIR,
        "archive_2025_05",
        "arch-expand-service-1",
        "u_arch_expand_service",
        "服务层冷库展开原文。",
        summary="service archived expansion card",
        original_created_at="2025-05-01 08:00:00",
    )
    result_set_id = await ResultSetService(svc.store).create_result_set(
        user_id="u_arch_expand_service",
        query_text="service archived expansion",
        memory_ids=["arch-expand-service-1"],
        metadata={"route": "memory_cards"},
    )

    expanded = await svc.expand_result(
        1,
        user_id="u_arch_expand_service",
        result_set_id=result_set_id,
    )

    assert expanded["_route"] == "result_set_expand"
    assert expanded["_raw_route"] == "archive"
    assert expanded["content"] == "服务层冷库展开原文。"


@pytest.mark.asyncio
async def test_archival_worker_archives_raw_card_memory_through_repository(tmp_path):
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository
    from agentmind.memory.service import MemoryService
    from agentmind.memory.workers.archival import run_archival

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    svc = MemoryService(repository=repo)
    old_created_at = (
        datetime.now(timezone.utc) - timedelta(days=120)
    ).strftime("%Y-%m-%d %H:%M:%S")
    await svc.write_memory({
        "memory_id": "archive-worker-card-1",
        "content": "归档 worker 应该压缩 raw_memory 内容。",
        "summary": "归档 worker raw/card",
        "user_id": "u_archive_worker",
        "source_agent": "codex",
        "created_at": old_created_at,
    })
    conn = repo.connect_sync()
    try:
        conn.execute(
            "UPDATE memory_cards SET score_metadata=json_set(score_metadata, '$.distilled', 1) WHERE memory_id=?",
            ("archive-worker-card-1",),
        )
        conn.commit()
    finally:
        conn.close()

    count = await run_archival(repo, {"archival_retention_days": 90})
    rows = await repo.search_archive(
        query="归档 worker",
        user_id="u_archive_worker",
        limit=5,
    )

    assert count == 1
    assert rows[0]["memory_id"] == "archive-worker-card-1"
    assert rows[0]["content"] == "归档 worker 应该压缩 raw_memory 内容。"
    assert await repo.get_raw("archive-worker-card-1", user_id="u_archive_worker") is None
