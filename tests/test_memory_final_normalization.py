import json


def _seed_legacy_memory_entries(repo):
    conn = repo._get_conn()
    try:
        rows = [
            (
                "legacy-1",
                "登录超时通过 session ttl 7200 解决。",
                "登录超时修复",
                "codex",
                "trace-1",
                "2026-05-29 10:00:00",
                "shared",
                json.dumps(["login"], ensure_ascii=False),
                "u1",
                "episodic",
                "conv-1",
                0.8,
            ),
            (
                "legacy-2",
                "检索只应该读取 memory_cards。",
                "卡片检索主路径",
                "codex",
                "trace-2",
                "2026-05-29 10:01:00",
                "private",
                json.dumps(["retrieval"], ensure_ascii=False),
                "u1",
                "semantic",
                "",
                0.7,
            ),
        ]
        conn.executemany(
            """INSERT OR REPLACE INTO memory_entries
               (memory_id, content, summary, source_agent, source_task_id, created_at,
                access_level, tags, user_id, memory_type, conversation_id, importance)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _table_count(repo, table_name: str) -> int:
    conn = repo._get_conn()
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    finally:
        conn.close()


def test_normalize_legacy_dry_run_does_not_write(tmp_path):
    from agentmind.memory.maintenance import MemoryMaintenance
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    _seed_legacy_memory_entries(repo)
    maintenance = MemoryMaintenance(repo)

    report = maintenance.normalize_legacy(apply=False)

    assert report.memory_entries_count == 2
    assert report.missing_raw_for_entries == 2
    assert report.missing_card_for_entries == 2
    assert _table_count(repo, "raw_memory") == 0
    assert _table_count(repo, "memory_cards") == 0


def test_normalize_legacy_apply_fills_raw_and_cards_idempotently(tmp_path):
    from agentmind.memory.maintenance import MemoryMaintenance
    from agentmind.memory.repository_sqlite import SqliteMemoryRepository

    repo = SqliteMemoryRepository(str(tmp_path / "memory.db"))
    _seed_legacy_memory_entries(repo)
    maintenance = MemoryMaintenance(repo)

    first = maintenance.normalize_legacy(apply=True)
    second = maintenance.normalize_legacy(apply=True)
    audit = maintenance.audit_legacy()

    assert first.memory_entries_count == 2
    assert second.memory_entries_count == 2
    assert _table_count(repo, "raw_memory") == 2
    assert _table_count(repo, "memory_cards") == 2
    assert audit.missing_raw_for_entries == 0
    assert audit.missing_card_for_entries == 0

    results = __import__("asyncio").run(
        repo.search_cards(query="登录超时", user_id="u1", limit=5)
    )
    assert results[0]["memory_id"] == "legacy-1"
    assert results[0]["raw_memory_id"] == "legacy-1"
    assert results[0]["tags"] == ["login"]
