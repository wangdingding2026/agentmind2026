import os

import pytest
import yaml

from agentmind.storage.db import (
    DATA_DIR,
    record_task_start,
    record_task_update,
    record_task_end,
    query_tasks,
    get_task_stats,
    get_task_detail,
    get_recent_errors,
    _enforce_history_lru,
    _MAX_RESULT_SIZE,
    get_db_connection,
)


class TestReadWrite:
    @pytest.mark.asyncio
    async def test_write_and_query(self, tmp_db):
        await record_task_start("tr-001", "写一个函数")
        await record_task_update("tr-001", "routing", matched_rule="code_kw", routed_agent="test_cli")
        await record_task_update("tr-001", "executing")
        await record_task_end("tr-001", "completed", "test_cli", 100, result="done")

        rows = await query_tasks(limit=10)
        assert len(rows) == 1
        assert rows[0]["trace_id"] == "tr-001"
        assert rows[0]["status"] == "completed"
        assert rows[0]["matched_rule"] == "code_kw"
        assert rows[0]["routed_agent"] == "test_cli"

    @pytest.mark.asyncio
    async def test_query_with_status_filter(self, tmp_db):
        await record_task_start("tr-001", "任务1")
        await record_task_start("tr-002", "任务2")
        await record_task_end("tr-001", "completed", "a1", 50, result="ok")
        await record_task_end("tr-002", "failed", "a2", error_message="err")

        completed = await query_tasks(status="completed")
        assert len(completed) == 1
        assert completed[0]["trace_id"] == "tr-001"

        failed = await query_tasks(status="failed")
        assert len(failed) == 1
        assert failed[0]["trace_id"] == "tr-002"


class TestStats:
    @pytest.mark.asyncio
    async def test_stats(self, tmp_db):
        await record_task_start("tr-001", "a")
        await record_task_end("tr-001", "completed", "a1", 100, result="ok")
        await record_task_start("tr-002", "b")
        await record_task_end("tr-002", "failed", "a1", error_message="err")
        await record_task_start("tr-003", "c")
        await record_task_end("tr-003", "completed", "a1", 200, result="ok2")

        stats = await get_task_stats()
        assert stats["total"] == 3
        assert stats["completed"] == 2
        assert stats["failed"] == 1
        assert stats["avg_execution_time_ms"] == 150  # (100+200)/2

    @pytest.mark.asyncio
    async def test_empty_db_stats(self, tmp_db):
        stats = await get_task_stats()
        assert stats["total"] == 0
        assert stats["avg_execution_time_ms"] == 0


class TestDetail:
    @pytest.mark.asyncio
    async def test_detail_found(self, tmp_db):
        await record_task_start("tr-001", "hello")
        await record_task_end("tr-001", "completed", "a1", 50, result="ok")

        detail = await get_task_detail("tr-001")
        assert detail is not None
        assert detail["trace_id"] == "tr-001"
        assert detail["result_summary"] == "ok"

    @pytest.mark.asyncio
    async def test_detail_not_found(self, tmp_db):
        detail = await get_task_detail("nonexistent")
        assert detail is None


class TestRecentErrors:
    @pytest.mark.asyncio
    async def test_recent_errors(self, tmp_db):
        await record_task_start("tr-001", "a")
        await record_task_end("tr-001", "failed", "a1", error_message="timeout")
        await record_task_start("tr-002", "b")
        await record_task_end("tr-002", "completed", "a1", 10, result="ok")
        await record_task_start("tr-003", "c")
        await record_task_end("tr-003", "failed", "a2", error_message="crash")

        errors = await get_recent_errors(limit=5)
        assert len(errors) == 2
        assert errors[0]["trace_id"] == "tr-003"  # 最新的在前

    @pytest.mark.asyncio
    async def test_recent_errors_empty(self, tmp_db):
        errors = await get_recent_errors()
        assert errors == []


class TestResultTruncation:
    @pytest.mark.asyncio
    async def test_large_result_truncated(self, tmp_db):
        big_result = "x" * (200 * 1024)  # 200KB
        await record_task_start("tr-big", "big")
        await record_task_end("tr-big", "completed", "a1", 100, result=big_result)

        detail = await get_task_detail("tr-big")
        assert detail is not None
        # 结果应该被截断
        saved_len = len(detail["result_summary"])
        assert saved_len <= 503  # 500 + "..."

    @pytest.mark.asyncio
    async def test_result_file_encoding(self, tmp_db):
        await record_task_start("tr-cn", "中文测试")
        await record_task_end("tr-cn", "completed", "a1", 10, result="你好世界")

        detail = await get_task_detail("tr-cn")
        assert detail is not None
        assert "你好世界" in detail["result_summary"]


class TestHistoryLRU:
    """history.db LRU 淘汰测试"""

    @pytest.mark.asyncio
    async def test_no_eviction_below_limit(self, tmp_db):
        """低于上限不淘汰"""
        settings = {"history": {"max_entries": 100, "retention_days": 30}}
        (tmp_db / "config" / "settings.yaml").write_text(
            yaml.dump(settings), encoding="utf-8"
        )
        for i in range(10):
            await record_task_start(f"tr-{i:03d}", f"task{i}")
            await record_task_end(f"tr-{i:03d}", "completed", "a1", 100, result="ok")

        stats = await get_task_stats()
        assert stats["total"] == 10

    @pytest.mark.asyncio
    async def test_max_entries_zero_unlimited(self, tmp_db):
        """max_entries=0 永不淘汰"""
        settings = {"history": {"max_entries": 0, "retention_days": 30}}
        (tmp_db / "config" / "settings.yaml").write_text(
            yaml.dump(settings), encoding="utf-8"
        )
        for i in range(20):
            await record_task_start(f"tr-{i:03d}", f"task{i}")
            await record_task_end(f"tr-{i:03d}", "completed", "a1", 100, result="ok")

        stats = await get_task_stats()
        assert stats["total"] == 20

    @pytest.mark.asyncio
    async def test_eviction_triggers_above_limit(self, tmp_db):
        """超过上限时淘汰最旧记录"""
        settings = {"history": {"max_entries": 10, "retention_days": 0}}
        (tmp_db / "config" / "settings.yaml").write_text(
            yaml.dump(settings), encoding="utf-8"
        )
        for i in range(15):
            await record_task_start(f"tr-{i:03d}", f"task{i}")
            await record_task_end(f"tr-{i:03d}", "completed", "a1", 100, result="ok")

        stats = await get_task_stats()
        assert stats["total"] <= 11  # 10 + 最多留一批（淘汰 10% = 1 at 10+1）

    @pytest.mark.asyncio
    async def test_retention_days_protects_recent(self, tmp_db):
        """retention_days 内记录不被淘汰"""
        settings = {"history": {"max_entries": 5, "retention_days": 365}}
        (tmp_db / "config" / "settings.yaml").write_text(
            yaml.dump(settings), encoding="utf-8"
        )
        for i in range(15):
            await record_task_start(f"tr-{i:03d}", f"task{i}")
            await record_task_end(f"tr-{i:03d}", "completed", "a1", 100, result="ok")

        # 所有记录都在 365 天内，不应被淘汰
        stats = await get_task_stats()
        assert stats["total"] == 15

    @pytest.mark.asyncio
    async def test_cascade_deletes_result_files(self, tmp_db):
        """淘汰时级联删除 results/*.txt"""
        settings = {"history": {"max_entries": 5, "retention_days": 0}}
        (tmp_db / "config" / "settings.yaml").write_text(
            yaml.dump(settings), encoding="utf-8"
        )
        for i in range(10):
            tid = f"tr-cascade-{i:03d}"
            await record_task_start(tid, f"task{i}")
            await record_task_end(tid, "completed", "a1", 100, result=f"result-{i}")

        # 检查旧记录的结果文件被删除
        results_dir = DATA_DIR / "results"
        remaining = list(results_dir.glob("tr-cascade-*.txt"))
        # 最多保留 max_entries 条的文件
        assert len(remaining) <= 6  # 5 + 最多 1 批淘汰后剩余

    @pytest.mark.asyncio
    async def test_direct_enforce_no_eviction_below_limit(self, tmp_db):
        """直接调用 _enforce_history_lru：低于上限不淘汰"""
        settings = {"history": {"max_entries": 100, "retention_days": 30}}
        (tmp_db / "config" / "settings.yaml").write_text(
            yaml.dump(settings), encoding="utf-8"
        )
        for i in range(5):
            await record_task_start(f"tr-d-{i:03d}", f"task{i}")
            await record_task_end(f"tr-d-{i:03d}", "completed", "a1", 100, result="ok")

        conn = get_db_connection()
        count_before = conn.execute("SELECT COUNT(*) as cnt FROM task_history").fetchone()["cnt"]
        _enforce_history_lru(conn)
        count_after = conn.execute("SELECT COUNT(*) as cnt FROM task_history").fetchone()["cnt"]
        conn.close()
        assert count_before == count_after == 5
