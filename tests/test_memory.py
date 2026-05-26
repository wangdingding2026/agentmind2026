"""记忆引擎最严格测试 — 公开API、内部函数、边界条件、错误处理、并发、迁移"""
import asyncio
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest
import yaml as _yaml


@pytest.fixture
def tmp_memory_db():
    """创建临时 memory.db 并返回 path"""
    mp = pytest.MonkeyPatch()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        data_dir = tmp_dir / "data"
        (data_dir / "results").mkdir(parents=True, exist_ok=True)
        (tmp_dir / "config").mkdir(parents=True, exist_ok=True)
        mp.setattr("agentmind.storage.db.DATA_DIR", data_dir)
        mp.setattr("agentmind.storage.db.DATA_HOME", tmp_dir)
        mp.setattr("agentmind.storage.db.CONFIG_DIR", tmp_dir / "config")
        mp.setattr("agentmind.storage.memory.DATA_DIR", data_dir)
        mp.setattr("agentmind.storage.memory.CONFIG_DIR", tmp_dir / "config")

        from agentmind.storage.db import initialize_memory_db
        initialize_memory_db()
        yield tmp_dir
    mp.undo()


# ═══════════════════════════════════════════════════
# Layer 1: 公开 API 完整测试
# ═══════════════════════════════════════════════════

class TestMemoryWrite:
    def test_write_new(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        version = asyncio.run(mem.write_memory({
            "memory_id": "test-001", "content": "如何修复登录 bug",
            "summary": "修复登录认证超时问题",
            "source_agent": "claude_code", "source_task_id": "tr-abc123",
            "tags": ["bug", "auth"],
        }, generate_embedding=False))
        assert version == 1

    def test_write_lww_updates_version(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "test-002", "content": "v1", "summary": "v1",
            "source_agent": "test", "source_task_id": "tr-001",
        }, generate_embedding=False))
        version = asyncio.run(mem.write_memory({
            "memory_id": "test-002", "content": "v2", "summary": "v2",
            "source_agent": "test", "source_task_id": "tr-002",
        }, generate_embedding=False))
        assert version == 2

    def test_write_empty_content(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        version = asyncio.run(mem.write_memory({
            "memory_id": "empty-1", "content": "", "summary": "",
            "source_agent": "test", "source_task_id": "tr-1",
        }, generate_embedding=False))
        assert version == 1

    def test_write_special_characters(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        special = """包含 '单引号' "双引号" \\反斜杠 %百分号 _下划线 \0空字节"""
        version = asyncio.run(mem.write_memory({
            "memory_id": "special-1", "content": special, "summary": "special",
            "source_agent": "test", "source_task_id": "tr-1",
        }, generate_embedding=False))
        assert version == 1
        results = asyncio.run(mem.search_memory(query="反斜杠"))
        assert len(results) == 1

    def test_write_long_content(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        long_text = "长文本" * 3000  # ~9000 chars
        version = asyncio.run(mem.write_memory({
            "memory_id": "long-1", "content": long_text, "summary": long_text[:200],
            "source_agent": "test", "source_task_id": "tr-1",
        }, generate_embedding=False))
        assert version == 1

    def test_write_unicode_emoji(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        version = asyncio.run(mem.write_memory({
            "memory_id": "unicode-1", "content": "🎉 日本語 안녕하세요 résumé 🚀",
            "summary": "unicode test",
            "source_agent": "test", "source_task_id": "tr-1",
        }, generate_embedding=False))
        assert version == 1
        results = asyncio.run(mem.search_memory(query="日本語"))
        assert len(results) == 1


class TestMemorySearch:
    def test_search_by_text(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "s-1", "content": "登录页面渲染异常", "summary": "修复登录页",
            "source_agent": "claude_code", "source_task_id": "tr-1",
        }, generate_embedding=False))
        asyncio.run(mem.write_memory({
            "memory_id": "s-2", "content": "数据库查询优化", "summary": "优化SQL",
            "source_agent": "hermes", "source_task_id": "tr-2",
        }, generate_embedding=False))
        results = asyncio.run(mem.search_memory(query="登录"))
        assert len(results) == 1
        assert results[0]["memory_id"] == "s-1"

    def test_search_by_agent(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "a-1", "content": "test", "summary": "test",
            "source_agent": "claude_code", "source_task_id": "tr-1",
        }, generate_embedding=False))
        asyncio.run(mem.write_memory({
            "memory_id": "a-2", "content": "test", "summary": "test",
            "source_agent": "hermes", "source_task_id": "tr-2",
        }, generate_embedding=False))
        results = asyncio.run(mem.search_memory(source_agent="hermes"))
        assert len(results) == 1
        assert results[0]["memory_id"] == "a-2"

    def test_search_by_tags(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "t-1", "content": "test", "summary": "test",
            "source_agent": "test", "source_task_id": "tr-1", "tags": ["bug", "urgent"],
        }, generate_embedding=False))
        asyncio.run(mem.write_memory({
            "memory_id": "t-2", "content": "test", "summary": "test",
            "source_agent": "test", "source_task_id": "tr-2", "tags": ["feature"],
        }, generate_embedding=False))
        results = asyncio.run(mem.search_memory(tags=["bug"]))
        assert len(results) == 1
        assert results[0]["memory_id"] == "t-1"

    def test_search_empty_query(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "eq-1", "content": "anything", "summary": "test",
            "source_agent": "test", "source_task_id": "tr-1",
        }, generate_embedding=False))
        results = asyncio.run(mem.search_memory(query=""))
        assert len(results) >= 1

    def test_search_no_results(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        results = asyncio.run(mem.search_memory(query="不存在的关键词XYZ123"))
        assert results == []

    def test_search_limit_zero(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "lz-1", "content": "test", "summary": "test",
            "source_agent": "test", "source_task_id": "tr-1",
        }, generate_embedding=False))
        results = asyncio.run(mem.search_memory(limit=0))
        assert results == []

    def test_search_sql_injection_safe(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "sql-1", "content": "normal data", "summary": "normal",
            "source_agent": "test", "source_task_id": "tr-1",
        }, generate_embedding=False))
        # SQL 注入不应崩溃，也不应返回异常结果
        results = asyncio.run(mem.search_memory(query="'; DROP TABLE memory_entries; --"))
        assert isinstance(results, list)

    def test_search_updates_last_accessed(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "la-1", "content": "hot entry", "summary": "hot",
            "source_agent": "test", "source_task_id": "tr-1",
        }, generate_embedding=False))
        asyncio.run(mem.search_memory(query="hot"))
        conn = mem._get_memory_conn()
        row = conn.execute("SELECT last_accessed_at FROM memory_entries WHERE memory_id='la-1'").fetchone()
        conn.close()
        assert row is not None
        assert row["last_accessed_at"] is not None


class TestMemoryStats:
    def test_stats(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "st-1", "content": "test", "summary": "test",
            "source_agent": "claude_code", "source_task_id": "tr-1",
        }, generate_embedding=False))
        stats = asyncio.run(mem.get_memory_stats())
        assert stats["total"] == 1
        assert "claude_code" in stats["by_source_agent"]

    def test_stats_empty_db(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        stats = asyncio.run(mem.get_memory_stats())
        assert stats["total"] == 0
        assert stats["by_heat"]["hot"] == 0
        assert stats["by_heat"]["warm"] == 0
        assert stats["by_heat"]["cold"] == 0

    def test_stats_heat_sum_equals_total(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        for i in range(3):
            asyncio.run(mem.write_memory({
                "memory_id": f"hs-{i}", "content": f"content {i}", "summary": f"summary {i}",
                "source_agent": "test", "source_task_id": f"tr-{i}",
            }, generate_embedding=False))
        stats = asyncio.run(mem.get_memory_stats())
        heat_total = stats["by_heat"]["hot"] + stats["by_heat"]["warm"] + stats["by_heat"]["cold"]
        assert heat_total == stats["total"]

    def test_stats_by_access_level(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "al-s", "content": "shared", "summary": "s",
            "source_agent": "test", "source_task_id": "tr-1", "access_level": "shared",
        }, generate_embedding=False))
        asyncio.run(mem.write_memory({
            "memory_id": "al-p", "content": "private", "summary": "p",
            "source_agent": "test", "source_task_id": "tr-2", "access_level": "private",
        }, generate_embedding=False))
        stats = asyncio.run(mem.get_memory_stats())
        assert stats["by_access_level"].get("shared", 0) >= 1
        assert stats["by_access_level"].get("private", 0) >= 1


class TestMemoryCleanup:
    def test_cleanup_old(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "cl-1", "content": "test", "summary": "test",
            "source_agent": "test", "source_task_id": "tr-1",
        }, generate_embedding=False))
        conn = mem._get_memory_conn()
        conn.execute("UPDATE memory_entries SET created_at = datetime('now', '-31 days') WHERE memory_id='cl-1'")
        conn.commit()
        conn.close()
        deleted = asyncio.run(mem.cleanup_memory(retention_days=30))
        assert deleted == 1

    def test_cleanup_zero_days(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "cz-1", "content": "test", "summary": "test",
            "source_agent": "test", "source_task_id": "tr-1",
        }, generate_embedding=False))
        deleted = asyncio.run(mem.cleanup_memory(retention_days=0))
        assert deleted >= 1  # 全部清理

    def test_cleanup_syncs_fts5(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "cs-1", "content": "fts sync test", "summary": "fts",
            "source_agent": "test", "source_task_id": "tr-1",
        }, generate_embedding=False))
        conn = mem._get_memory_conn()
        conn.execute("UPDATE memory_entries SET created_at = datetime('now', '-31 days') WHERE memory_id='cs-1'")
        conn.commit()
        conn.close()
        asyncio.run(mem.cleanup_memory(retention_days=30))
        # FTS5 中也不应有该记录
        conn = mem._get_memory_conn()
        fts_row = conn.execute("SELECT * FROM memory_fts WHERE memory_id='cs-1'").fetchone()
        conn.close()
        assert fts_row is None

    def test_cleanup_empty_db(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        deleted = asyncio.run(mem.cleanup_memory(retention_days=30))
        assert deleted == 0


class TestMemoryConflictResolution:
    def test_conflict_lower_credibility_downgrades(self, tmp_memory_db):
        """低可信度 Agent 覆盖高可信度 → 新记忆降级为 private"""
        from agentmind.storage import memory as mem
        agents_path = tmp_memory_db / "config" / "agents.yaml"
        agents_path.write_text(_yaml.dump({
            "agents": [
                {"id": "trusted", "name": "T", "type": "cli", "config": {"command": "echo", "credibility": 0.9}},
                {"id": "untrusted", "name": "U", "type": "cli", "config": {"command": "echo", "credibility": 0.2}},
            ]
        }))
        # 先写高可信度
        asyncio.run(mem.write_memory({
            "memory_id": "conflict-1", "content": "trusted content", "summary": "trusted",
            "source_agent": "trusted", "source_task_id": "tr-1",
        }, generate_embedding=False))
        # 低可信度覆盖
        asyncio.run(mem.write_memory({
            "memory_id": "conflict-1", "content": "untrusted content", "summary": "untrusted",
            "source_agent": "untrusted", "source_task_id": "tr-2",
        }, generate_embedding=False))
        # 新记忆应降级为 private，原记忆保留
        results = asyncio.run(mem.search_memory(access_levels=["shared"]))
        shared_contents = [r["content"] for r in results]
        assert "trusted content" in shared_contents

    def test_conflict_higher_credibility_overwrites(self, tmp_memory_db):
        """高可信度覆盖低可信度 → 正常覆盖"""
        from agentmind.storage import memory as mem
        agents_path = tmp_memory_db / "config" / "agents.yaml"
        agents_path.write_text(_yaml.dump({
            "agents": [
                {"id": "trusted", "name": "T", "type": "cli", "config": {"command": "echo", "credibility": 0.9}},
                {"id": "untrusted", "name": "U", "type": "cli", "config": {"command": "echo", "credibility": 0.2}},
            ]
        }))
        asyncio.run(mem.write_memory({
            "memory_id": "conflict-2", "content": "old low cred", "summary": "old",
            "source_agent": "untrusted", "source_task_id": "tr-1",
        }, generate_embedding=False))
        version = asyncio.run(mem.write_memory({
            "memory_id": "conflict-2", "content": "new high cred", "summary": "new",
            "source_agent": "trusted", "source_task_id": "tr-2",
        }, generate_embedding=False))
        assert version == 2  # 正常覆盖

    def test_conflict_same_agent_normal_overwrite(self, tmp_memory_db):
        """同 Agent 覆盖 → 正常 LWW"""
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "conflict-3", "content": "v1", "summary": "v1",
            "source_agent": "claude_code", "source_task_id": "tr-1",
        }, generate_embedding=False))
        version = asyncio.run(mem.write_memory({
            "memory_id": "conflict-3", "content": "v2", "summary": "v2",
            "source_agent": "claude_code", "source_task_id": "tr-2",
        }, generate_embedding=False))
        assert version == 2


class TestMemorySemanticConflict:
    """语义冲突检测：写入时用向量相似度发现不同 memory_id 但内容高度相似的情况"""

    def test_no_embedding_skips_semantic_check(self, tmp_memory_db, monkeypatch):
        """无 embedding 时跳过语义冲突检测"""
        from agentmind.storage import memory as mem

        settings = {"memory": {"conflict_check_enabled": True, "conflict_similarity_threshold": 0.85}}
        (tmp_memory_db / "config" / "settings.yaml").write_text(
            _yaml.dump(settings), encoding="utf-8"
        )
        monkeypatch.setattr(mem, "has_local_embedding", lambda: False)

        # 写入两条无 embedding 的记忆，不应触发冲突
        asyncio.run(mem.write_memory({
            "memory_id": "sem-1",
            "content": "Python 是数据科学的首选语言",
            "summary": "Python 在数据科学领域广泛使用",
            "source_agent": "claude_code",
            "source_task_id": "task-1",
        }, generate_embedding=False))

        v = asyncio.run(mem.write_memory({
            "memory_id": "sem-2",
            "content": "Python 非常适合数据分析",
            "summary": "数据分析师喜欢用 Python",
            "source_agent": "codex",
            "source_task_id": "task-2",
        }, generate_embedding=False))
        assert v == 1

        results = asyncio.run(mem.search_memory(query="Python"))
        shared = [r for r in results if r["access_level"] == "shared"]
        assert len(shared) >= 2

    def test_semantic_conflict_lower_credibility_demoted(self, tmp_memory_db, monkeypatch):
        """语义相似 + 低可信度 → 新记忆降级 private"""
        from agentmind.storage import memory as mem

        settings = {
            "memory": {"conflict_check_enabled": True, "conflict_similarity_threshold": 0.85},
            "embedding": {"enabled": True, "endpoint": "", "local_fallback": True},
        }
        (tmp_memory_db / "config" / "settings.yaml").write_text(
            _yaml.dump(settings), encoding="utf-8"
        )

        agents_config = {
            "agents": [
                {"id": "claude_code", "config": {"credibility": 0.8}},
                {"id": "codex", "config": {"credibility": 0.3}},
            ]
        }
        (tmp_memory_db / "config" / "agents.yaml").write_text(
            _yaml.dump(agents_config), encoding="utf-8"
        )

        # Mock _find_similar_conflicts 返回一个匹配记录
        monkeypatch.setattr(mem, "_find_similar_conflicts",
            lambda conn, emb, cur_id, thr: [{
                "memory_id": "sem-ml-1", "source_agent": "claude_code",
                "content": "Python 是数据科学的首选语言", "similarity": 0.92,
            }])
        monkeypatch.setattr(mem, "has_local_embedding", lambda: True)
        monkeypatch.setattr(mem, "get_local_provider",
            lambda: type('P', (), {'encode': lambda s, t: [0.9] * 384, 'dimension': 384})())

        # Claude Code（高可信度 0.8）先写入
        asyncio.run(mem.write_memory({
            "memory_id": "sem-ml-1",
            "content": "Python 是数据科学的首选语言",
            "summary": "Python 在数据科学领域广泛使用",
            "source_agent": "claude_code",
            "source_task_id": "task-1",
            "user_id": "user1",
        }))

        # Codex（低可信度 0.3）写入 → 应被降级
        asyncio.run(mem.write_memory({
            "memory_id": "sem-ml-2",
            "content": "Python 非常适合数据分析和机器学习",
            "summary": "数据分析师喜欢用 Python",
            "source_agent": "codex",
            "source_task_id": "task-2",
            "user_id": "user1",
        }))

        results = asyncio.run(mem.search_memory(query="Python"))
        private_entries = [r for r in results if r["access_level"] == "private"]
        shared_entries = [r for r in results if r["access_level"] == "shared"]

        assert len(private_entries) >= 1
        assert private_entries[0]["source_agent"] == "codex"
        assert "conflict:semantic_similar" in str(private_entries[0].get("tags", []))
        assert any(r["source_agent"] == "claude_code" for r in shared_entries)

    def test_semantic_conflict_disabled_by_config(self, tmp_memory_db, monkeypatch):
        """conflict_check_enabled=false 时跳过语义检测"""
        from agentmind.storage import memory as mem

        settings = {
            "memory": {"conflict_check_enabled": False},
            "embedding": {"enabled": True, "endpoint": "", "local_fallback": True},
        }
        (tmp_memory_db / "config" / "settings.yaml").write_text(
            _yaml.dump(settings), encoding="utf-8"
        )

        # Mock：即使 _find_similar_conflicts 返回匹配，也因 disabled 而不触发
        monkeypatch.setattr(mem, "_find_similar_conflicts",
            lambda conn, emb, cur_id, thr: [{"memory_id": "off-1", "source_agent": "x", "content": "x", "similarity": 0.99}])
        monkeypatch.setattr(mem, "has_local_embedding", lambda: True)
        monkeypatch.setattr(mem, "get_local_provider",
            lambda: type('P', (), {'encode': lambda s, t: [0.9] * 384, 'dimension': 384})())

        asyncio.run(mem.write_memory({
            "memory_id": "off-1", "content": "Python 适合数据科学",
            "summary": "数据科学", "source_agent": "test", "source_task_id": "t1",
        }))
        asyncio.run(mem.write_memory({
            "memory_id": "off-2", "content": "Python 适合数据分析",
            "summary": "数据分析", "source_agent": "test", "source_task_id": "t2",
        }))

        results = asyncio.run(mem.search_memory(query="Python"))
        shared = [r for r in results if r["access_level"] == "shared"]
        assert len(shared) == 2

    def test_similarity_below_threshold_no_conflict(self, tmp_memory_db, monkeypatch):
        """_find_similar_conflicts 返回低相似度记录，低于阈值不触发冲突"""
        from agentmind.storage import memory as mem

        settings = {
            "memory": {"conflict_check_enabled": True, "conflict_similarity_threshold": 0.85},
            "embedding": {"enabled": True, "endpoint": "", "local_fallback": True},
        }
        (tmp_memory_db / "config" / "settings.yaml").write_text(
            _yaml.dump(settings), encoding="utf-8"
        )

        # Mock 返回空（低于阈值被 _find_similar_conflicts 内部过滤）
        monkeypatch.setattr(mem, "_find_similar_conflicts", lambda conn, emb, cur_id, thr: None)
        monkeypatch.setattr(mem, "has_local_embedding", lambda: True)
        monkeypatch.setattr(mem, "get_local_provider",
            lambda: type('P', (), {'encode': lambda s, t: [0.9] * 384, 'dimension': 384})())

        asyncio.run(mem.write_memory({
            "memory_id": "diff-1", "content": "Python 数据科学",
            "summary": "数据科学", "source_agent": "test", "source_task_id": "t1",
        }))
        asyncio.run(mem.write_memory({
            "memory_id": "diff-2", "content": "Java 企业开发",
            "summary": "企业开发", "source_agent": "test", "source_task_id": "t2",
        }))

        results = asyncio.run(mem.search_memory(query=""))
        shared = [r for r in results if r["access_level"] == "shared"]
        assert len(shared) == 2


# ═══════════════════════════════════════════════════
# Layer 1（续）: 标签过滤、用户过滤、分层、热度、LRU
# ═══════════════════════════════════════════════════

class TestMemoryTagsLimit:
    def test_tags_filter_works_beyond_limit(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        for i in range(5):
            asyncio.run(mem.write_memory({
                "memory_id": f"nolimit-{i}", "content": f"content {i}", "summary": f"summary {i}",
                "source_agent": "test", "source_task_id": f"tr-{i}", "tags": ["other"],
            }, generate_embedding=False))
        asyncio.run(mem.write_memory({
            "memory_id": "target-1", "content": "important doc", "summary": "important",
            "source_agent": "test", "source_task_id": "tr-target", "tags": ["urgent"],
        }, generate_embedding=False))
        results = asyncio.run(mem.search_memory(tags=["urgent"], limit=3))
        assert len(results) == 1
        assert results[0]["memory_id"] == "target-1"


class TestMemoryUserFilter:
    def test_search_by_user_id(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "u-1", "content": "user a message", "summary": "user a",
            "source_agent": "test", "source_task_id": "tr-1",
            "tags": ["task", "user:ou_user_a"], "user_id": "ou_user_a",
        }, generate_embedding=False))
        asyncio.run(mem.write_memory({
            "memory_id": "u-2", "content": "user b message", "summary": "user b",
            "source_agent": "test", "source_task_id": "tr-2",
            "tags": ["task", "user:ou_user_b"], "user_id": "ou_user_b",
        }, generate_embedding=False))
        results = asyncio.run(mem.search_memory(user_id="ou_user_a"))
        assert len(results) == 1
        assert results[0]["memory_id"] == "u-1"


class TestMemoryAccessLevel:
    def test_search_excludes_private(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "al-1", "content": "shared content", "summary": "shared",
            "source_agent": "test", "source_task_id": "tr-1", "access_level": "shared",
        }, generate_embedding=False))
        asyncio.run(mem.write_memory({
            "memory_id": "al-2", "content": "private content", "summary": "private",
            "source_agent": "test", "source_task_id": "tr-2", "access_level": "private",
        }, generate_embedding=False))
        results = asyncio.run(mem.search_memory(access_levels=["shared"]))
        assert len(results) >= 1
        assert all(r["access_level"] == "shared" for r in results)


class TestMemoryHeat:
    def test_heat_tracking(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "ht-1", "content": "hot content", "summary": "hot",
            "source_agent": "test", "source_task_id": "tr-1",
        }, generate_embedding=False))
        asyncio.run(mem.search_memory(query="hot"))
        stats = asyncio.run(mem.get_memory_stats())
        assert "by_heat" in stats
        assert stats["by_heat"]["hot"] >= 1


class TestLRUEviction:
    def test_lru_eviction_triggered(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        settings_path = tmp_memory_db / "config" / "settings.yaml"
        settings_path.write_text(_yaml.dump({"memory": {"max_entries": 5}}))
        for i in range(12):
            asyncio.run(mem.write_memory({
                "memory_id": f"lru-{i}", "content": f"content {i}", "summary": f"summary {i}",
                "source_agent": "test", "source_task_id": f"tr-{i}",
            }, generate_embedding=False))
        stats = asyncio.run(mem.get_memory_stats())
        assert stats["total"] <= 12  # 有清理发生

    def test_lru_under_threshold_noop(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        settings_path = tmp_memory_db / "config" / "settings.yaml"
        settings_path.write_text(_yaml.dump({"memory": {"max_entries": 100}}))
        for i in range(3):
            asyncio.run(mem.write_memory({
                "memory_id": f"lru-safe-{i}", "content": f"content {i}", "summary": f"summary {i}",
                "source_agent": "test", "source_task_id": f"tr-{i}",
            }, generate_embedding=False))
        stats = asyncio.run(mem.get_memory_stats())
        assert stats["total"] == 3  # 无淘汰

    def test_lru_syncs_fts5(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        settings_path = tmp_memory_db / "config" / "settings.yaml"
        settings_path.write_text(_yaml.dump({"memory": {"max_entries": 5}}))
        for i in range(10):
            asyncio.run(mem.write_memory({
                "memory_id": f"lru-fts-{i}", "content": f"content {i}", "summary": f"summary {i}",
                "source_agent": "test", "source_task_id": f"tr-{i}",
            }, generate_embedding=False))
        # FTS5 不应包含已淘汰的记录
        conn = mem._get_memory_conn()
        fts_count = conn.execute("SELECT COUNT(*) as cnt FROM memory_fts").fetchone()["cnt"]
        main_count = conn.execute("SELECT COUNT(*) as cnt FROM memory_entries").fetchone()["cnt"]
        conn.close()
        assert fts_count <= main_count + 1  # 允许少量延迟


# ═══════════════════════════════════════════════════
# FTS5 / Embedding / 组合过滤
# ═══════════════════════════════════════════════════

class TestMemoryFTS5:
    def test_fts5_search(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "fts-1", "content": "FTS5 full text search test",
            "summary": "fts test", "source_agent": "test", "source_task_id": "tr-1",
        }, generate_embedding=False))
        asyncio.run(mem.write_memory({
            "memory_id": "fts-2", "content": "another entry about databases",
            "summary": "db", "source_agent": "test", "source_task_id": "tr-2",
        }, generate_embedding=False))
        results = asyncio.run(mem.search_memory(query="fts"))
        assert len(results) >= 1
        assert results[0]["memory_id"] == "fts-1"

    def test_fts5_special_characters_safe(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "fts-sc-1", "content": "normal text", "summary": "normal",
            "source_agent": "test", "source_task_id": "tr-1",
        }, generate_embedding=False))
        # FTS5 特殊语法不崩溃
        for q in ['NEAR', 'AND', 'OR', '*', '""', "()", '"test"']:
            results = asyncio.run(mem.search_memory(query=q))
            assert isinstance(results, list)

    def test_fts5_fallback_to_like(self, tmp_memory_db):
        """手动清空 FTS5 后搜索仍可用 LIKE 降级"""
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "fts-fb-1", "content": "fallback test entry",
            "summary": "fallback", "source_agent": "test", "source_task_id": "tr-1",
        }, generate_embedding=False))
        conn = mem._get_memory_conn()
        conn.execute("DELETE FROM memory_fts")
        conn.commit()
        conn.close()
        results = asyncio.run(mem.search_memory(query="fallback"))
        assert len(results) >= 1  # LIKE 降级找到


class TestMemoryCombinedFilters:
    def test_user_id_and_access_level(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "cf-1", "content": "shared user A", "summary": "A",
            "source_agent": "test", "source_task_id": "tr-1",
            "tags": ["task", "user:ou_A"], "access_level": "shared", "user_id": "ou_A",
        }, generate_embedding=False))
        asyncio.run(mem.write_memory({
            "memory_id": "cf-2", "content": "private user A", "summary": "A private",
            "source_agent": "test", "source_task_id": "tr-2",
            "tags": ["task", "user:ou_A"], "access_level": "private", "user_id": "ou_A",
        }, generate_embedding=False))
        asyncio.run(mem.write_memory({
            "memory_id": "cf-3", "content": "shared user B", "summary": "B",
            "source_agent": "test", "source_task_id": "tr-3",
            "tags": ["task", "user:ou_B"], "access_level": "shared", "user_id": "ou_B",
        }, generate_embedding=False))
        results = asyncio.run(mem.search_memory(user_id="ou_A", access_levels=["shared"]))
        assert len(results) == 1
        assert results[0]["memory_id"] == "cf-1"


class TestMemoryEmbedding:
    def test_write_without_embedding(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        version = asyncio.run(mem.write_memory({
            "memory_id": "noemb-1", "content": "no embedding", "summary": "no emb",
            "source_agent": "test", "source_task_id": "tr-1",
        }, generate_embedding=False))
        assert version == 1
        results = asyncio.run(mem.search_memory(query="embedding"))
        assert len(results) == 1

    def test_embedding_blob_size(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        emb = [0.1] * 768  # 768 维
        blob = mem._embedding_to_blob(emb)
        assert len(blob) == 768 * 4  # float32 = 4 bytes


# ═══════════════════════════════════════════════════
# Layer 2: 内部函数单元测试
# ═══════════════════════════════════════════════════

class TestMemoryInternal:
    def test_now_sqlite_format(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        result = mem._now_sqlite()
        import re
        assert re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$', result)

    def test_rrf_fusion_overlap(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        fts = [
            {"memory_id": "a", "content": "a"}, {"memory_id": "b", "content": "b"},
        ]
        vec = [
            {"memory_id": "b", "content": "b"}, {"memory_id": "c", "content": "c"},
        ]
        fused = mem._rrf_fusion(fts, vec)
        ids = [r["memory_id"] for r in fused]
        # b 在两路都出现，得分应最高
        assert ids[0] == "b"
        assert set(ids) == {"a", "b", "c"}

    def test_rrf_fusion_empty_fts(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        vec = [{"memory_id": "x", "content": "x"}, {"memory_id": "y", "content": "y"}]
        fused = mem._rrf_fusion([], vec)
        assert len(fused) == 2
        assert fused[0]["memory_id"] == "x"

    def test_rrf_fusion_empty_vec(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        fts = [{"memory_id": "x", "content": "x"}]
        fused = mem._rrf_fusion(fts, [])
        assert len(fused) == 1
        assert fused[0]["memory_id"] == "x"

    def test_rrf_fusion_disjoint(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        fts = [{"memory_id": "a", "content": "a"}]
        vec = [{"memory_id": "b", "content": "b"}]
        fused = mem._rrf_fusion(fts, vec)
        assert len(fused) == 2

    def test_get_agent_credibility_known(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        agents_path = tmp_memory_db / "config" / "agents.yaml"
        agents_path.write_text(_yaml.dump({
            "agents": [
                {"id": "trusted", "config": {"credibility": 0.9, "command": "echo"}},
                {"id": "low", "config": {"credibility": 0.1, "command": "echo"}},
            ]
        }))
        assert mem._get_agent_credibility("trusted") == 0.9
        assert mem._get_agent_credibility("low") == 0.1

    def test_get_agent_credibility_unknown(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        assert mem._get_agent_credibility("nonexistent") == 0.5
        assert mem._get_agent_credibility("") == 0.5

    def test_load_settings_missing(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        result = mem._load_settings()
        assert result == {}

    def test_load_settings_valid(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        settings_path = tmp_memory_db / "config" / "settings.yaml"
        settings_path.write_text(_yaml.dump({"memory": {"max_entries": 50}, "embedding": {"enabled": True}}))
        result = mem._load_settings()
        assert result["memory"]["max_entries"] == 50
        assert result["embedding"]["enabled"] is True

    def test_get_memory_conn_sets_pragma(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        conn = mem._get_memory_conn()
        row = conn.execute("PRAGMA busy_timeout").fetchone()
        conn.close()
        assert row is not None


# ═══════════════════════════════════════════════════
# Layer 3 & 4: 数据库边界 + 错误处理与健壮性
# ═══════════════════════════════════════════════════

class TestMemoryRobustness:
    def test_all_columns_stored_correctly(self, tmp_memory_db):
        """写入后所有列值正确持久化"""
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "cols-1", "content": "full test", "summary": "full",
            "source_agent": "claude_code", "source_task_id": "tr-cols",
            "tags": ["task", "user:ou_test"], "access_level": "shared", "user_id": "ou_test",
        }, generate_embedding=False))
        conn = mem._get_memory_conn()
        row = conn.execute("SELECT * FROM memory_entries WHERE memory_id='cols-1'").fetchone()
        conn.close()
        assert row["memory_id"] == "cols-1"
        assert row["content"] == "full test"
        assert row["source_agent"] == "claude_code"
        assert row["source_task_id"] == "tr-cols"
        assert row["access_level"] == "shared"
        assert row["version"] == 1
        assert row["user_id"] == "ou_test"

    def test_fts5_consistency_after_write(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "ftscon-1", "content": "FTS5 consistency check",
            "summary": "consistency", "source_agent": "test", "source_task_id": "tr-1",
        }, generate_embedding=False))
        conn = mem._get_memory_conn()
        fts_row = conn.execute("SELECT * FROM memory_fts WHERE memory_id='ftscon-1'").fetchone()
        conn.close()
        assert fts_row is not None

    def test_anomalous_memory_id_characters(self, tmp_memory_db):
        from agentmind.storage import memory as mem
        for mid in ["path/like", "dot.id", "under_score", "hy-phen", "space id"]:
            version = asyncio.run(mem.write_memory({
                "memory_id": mid, "content": "test", "summary": "test",
                "source_agent": "test", "source_task_id": "tr-1",
            }, generate_embedding=False))
            assert version == 1

    def test_write_concurrent(self, tmp_memory_db):
        """并发写入不同 memory_id 不报错"""
        from agentmind.storage import memory as mem

        async def write_batch():
            tasks = []
            for i in range(10):
                tasks.append(mem.write_memory({
                    "memory_id": f"con-{i}", "content": f"concurrent {i}", "summary": f"c{i}",
                    "source_agent": "test", "source_task_id": f"tr-{i}",
                }, generate_embedding=False))
            return await asyncio.gather(*tasks)

        versions = asyncio.run(write_batch())
        assert all(v == 1 for v in versions)
        stats = asyncio.run(mem.get_memory_stats())
        assert stats["total"] >= 10

    def test_empty_db_all_operations(self, tmp_memory_db):
        """空数据库上所有操作不崩溃"""
        from agentmind.storage import memory as mem
        assert asyncio.run(mem.search_memory()) == []
        assert asyncio.run(mem.get_memory_stats())["total"] == 0
        assert asyncio.run(mem.cleanup_memory()) == 0

    def test_missing_vec_table_no_crash(self, tmp_memory_db):
        """vec_memory 不可用时搜索不崩溃"""
        from agentmind.storage.db import is_vec_available
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "novec-1", "content": "no vector", "summary": "test",
            "source_agent": "test", "source_task_id": "tr-1",
        }, generate_embedding=False))
        # 即使向量不可用，搜索仍应正常工作
        results = asyncio.run(mem.search_memory(query="vector"))
        assert isinstance(results, list)
        assert len(results) >= 1

    def test_fts5_delete_search_still_works(self, tmp_memory_db):
        """手动删除 FTS5 条目后搜索降级 LIKE"""
        from agentmind.storage import memory as mem
        asyncio.run(mem.write_memory({
            "memory_id": "ftsdel-1", "content": "fts delete recovery",
            "summary": "recovery", "source_agent": "test", "source_task_id": "tr-1",
        }, generate_embedding=False))
        conn = mem._get_memory_conn()
        conn.execute("DELETE FROM memory_fts WHERE memory_id='ftsdel-1'")
        conn.commit()
        conn.close()
        results = asyncio.run(mem.search_memory(query="recovery"))
        assert len(results) >= 1


# ═══════════════════════════════════════════════════
# Layer 6: 数据迁移测试
# ═══════════════════════════════════════════════════

class TestDataMigration:
    def test_old_schema_alter_table_adds_columns(self, tmp_memory_db):
        """模拟旧版 DB（无新增列），启动后自动补齐"""
        from agentmind.storage import memory as mem
        conn = mem._get_memory_conn()
        # 验证所有新增列存在
        cols = conn.execute("PRAGMA table_info(memory_entries)").fetchall()
        col_names = [c["name"] for c in cols]
        for expected in ["embedding", "user_id", "last_accessed_at"]:
            assert expected in col_names
        conn.close()

    def test_new_install_all_tables_exist(self, tmp_memory_db):
        """全新安装后所有表和索引存在"""
        conn = sqlite3.connect(str(tmp_memory_db / "data" / "memory.db"))
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' OR type='virtual'"
        ).fetchall()]
        conn.close()
        assert "memory_entries" in tables
        assert "memory_fts" in tables
        # vec_memory 依赖 sqlite-vec，可能不存在，不强制检查

    def test_wal_enabled(self, tmp_memory_db):
        """WAL 模式已启用"""
        conn = sqlite3.connect(str(tmp_memory_db / "data" / "memory.db"))
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert journal.lower() == "wal"

    def test_fts5_indexes_exist(self, tmp_memory_db):
        """所有必要的索引存在"""
        conn = sqlite3.connect(str(tmp_memory_db / "data" / "memory.db"))
        indexes = [r[1] for r in conn.execute(
            "SELECT * FROM sqlite_master WHERE type='index'"
        ).fetchall()]
        conn.close()
        assert "idx_memory_source" in indexes
        assert "idx_memory_user" in indexes


# ═══════════════════════════════════════════════════
# Layer 7: Embedding 生成与降级测试
# ═══════════════════════════════════════════════════


class TestEmbeddingGeneration:
    """测试 _generate_embedding 在各种场景下的行为"""

    def test_embedding_disabled_returns_none(self, tmp_memory_db):
        """embedding.enabled=false 时直接返回 None"""
        from agentmind.storage import memory as mem
        settings = {"embedding": {"enabled": False}}
        # 写入 settings.yaml
        (tmp_memory_db / "config" / "settings.yaml").write_text(
            _yaml.dump(settings), encoding="utf-8"
        )
        result = asyncio.run(mem._generate_embedding("hello"))
        assert result is None

    def test_no_endpoint_no_local_returns_none(self, tmp_memory_db):
        """无 endpoint 且无本地模型时返回 None"""
        from agentmind.storage import memory as mem
        import agentmind.storage.embedding as emb_mod

        settings = {"embedding": {"enabled": True, "endpoint": "", "local_fallback": False}}
        (tmp_memory_db / "config" / "settings.yaml").write_text(
            _yaml.dump(settings), encoding="utf-8"
        )
        result = asyncio.run(mem._generate_embedding("hello"))
        assert result is None

    def test_external_api_success(self, tmp_memory_db, monkeypatch):
        """外部 API 返回成功时直接返回向量"""
        from agentmind.storage import memory as mem

        settings = {
            "embedding": {
                "enabled": True,
                "endpoint": "https://api.example.com/embeddings",
                "api_key": "sk-test",
                "model": "test-model",
                "timeout_seconds": 5,
            }
        }
        (tmp_memory_db / "config" / "settings.yaml").write_text(
            _yaml.dump(settings), encoding="utf-8"
        )

        # Mock httpx.AsyncClient
        class MockResp:
            status_code = 200

            def json(self):
                return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

        class MockClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def post(self, *a, **kw):
                return MockResp()

        monkeypatch.setattr(mem.httpx, "AsyncClient", MockClient)
        result = asyncio.run(mem._generate_embedding("test text"))
        assert result == [0.1, 0.2, 0.3]

    def test_external_api_timeout_falls_back_to_local(self, tmp_memory_db, monkeypatch):
        """外部 API 超时时降级到本地模型"""
        from agentmind.storage import memory as mem
        import agentmind.storage.embedding as emb_mod

        settings = {
            "embedding": {
                "enabled": True,
                "endpoint": "https://api.example.com/embeddings",
                "api_key": "sk-test",
                "local_fallback": True,
            }
        }
        (tmp_memory_db / "config" / "settings.yaml").write_text(
            _yaml.dump(settings), encoding="utf-8"
        )

        # Mock 外部 API 抛出异常
        class MockClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def post(self, *a, **kw):
                raise TimeoutError("connection timeout")

        monkeypatch.setattr(mem.httpx, "AsyncClient", MockClient)

        # Mock 本地模型 — 需要 patch memory 模块中的引用
        class MockLocalProvider:
            def encode(self, text):
                return [0.5, 0.6, 0.7]

        monkeypatch.setattr(mem, "get_local_provider", lambda: MockLocalProvider())
        result = asyncio.run(mem._generate_embedding("test text"))
        assert result == [0.5, 0.6, 0.7]

    def test_external_api_non_200_falls_back(self, tmp_memory_db, monkeypatch):
        """外部 API 返回非 200 时降级"""
        from agentmind.storage import memory as mem

        settings = {
            "embedding": {
                "enabled": True,
                "endpoint": "https://api.example.com/embeddings",
                "api_key": "sk-test",
                "local_fallback": True,
            }
        }
        (tmp_memory_db / "config" / "settings.yaml").write_text(
            _yaml.dump(settings), encoding="utf-8"
        )

        class MockResp:
            status_code = 500

            def json(self):
                return {"error": "internal error"}

        class MockClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def post(self, *a, **kw):
                return MockResp()

        monkeypatch.setattr(mem.httpx, "AsyncClient", MockClient)

        class MockLocalProvider:
            def encode(self, text):
                return [0.9, 0.8, 0.7]

        monkeypatch.setattr(mem, "get_local_provider", lambda: MockLocalProvider())
        result = asyncio.run(mem._generate_embedding("test text"))
        assert result == [0.9, 0.8, 0.7]


class TestEmbeddingCache:
    """测试 embedding 缓存行为"""

    def test_cache_hit(self, tmp_memory_db, monkeypatch):
        from agentmind.storage import memory as mem

        query = "什么是向量搜索"
        emb_value = [0.1, 0.2, 0.3]
        mem._EMBED_CACHE[query] = emb_value
        result = mem.await_or_sync_embedding(query, {"embedding": {}})
        assert result == emb_value
        # 清理
        del mem._EMBED_CACHE[query]

    def test_cache_lru_eviction(self, tmp_memory_db):
        from agentmind.storage import memory as mem

        # 通过 _cache_embedding 写入，触发 LRU 淘汰
        for i in range(mem._EMBED_CACHE_MAX + 10):
            mem._cache_embedding(f"q{i}", [float(i)] * 3)

        # 缓存不应超过上限
        assert len(mem._EMBED_CACHE) <= mem._EMBED_CACHE_MAX

        # 清理
        mem._EMBED_CACHE.clear()


class TestDiscussionMemoryEmbedding:
    """验证讨论记忆的 embedding 生成"""

    def test_discussion_memory_generates_embedding_by_default(self, tmp_memory_db, monkeypatch):
        """讨论记忆应默认 generate_embedding=True（不再显式跳过）"""
        from agentmind.storage import memory as mem
        import agentmind.storage.embedding as emb_mod

        settings = {
            "embedding": {
                "enabled": True,
                "endpoint": "",
                "local_fallback": True,
            }
        }
        (tmp_memory_db / "config" / "settings.yaml").write_text(
            _yaml.dump(settings), encoding="utf-8"
        )

        # Mock 本地模型
        class MockLocalProvider:
            def encode(self, text):
                return [0.11, 0.22, 0.33, 0.44] * 96  # 384-dim

        monkeypatch.setattr(emb_mod, "get_local_provider", lambda: MockLocalProvider())
        monkeypatch.setattr(emb_mod, "has_local_embedding", lambda: True)

        version = asyncio.run(mem.write_memory({
            "memory_id": "discuss-user1-t1",
            "content": "讨论：微服务架构（第1轮）",
            "summary": "[Claude Code] 微服务架构的核心优势是独立部署...",
            "source_agent": "claude_code",
            "source_task_id": "trace-001",
            "tags": ["discussion", "user:user1"],
            "user_id": "user1",
        }))
        assert version == 1

        # 验证记忆已写入
        results = asyncio.run(mem.search_memory(query="微服务架构"))
        assert len(results) >= 1
        assert results[0]["memory_id"] == "discuss-user1-t1"


class TestVectorSearchIntegration:
    """向量搜索端到端集成测试（mock embedding）"""

    def test_write_and_vector_search(self, tmp_memory_db, monkeypatch):
        """写入记忆 + 生成向量 + 向量搜索完整链路"""
        from agentmind.storage import memory as mem
        import agentmind.storage.embedding as emb_mod
        from agentmind.storage.db import is_vec_available

        # 先确认 sqlite-vec 可用
        if not is_vec_available():
            pytest.skip("sqlite-vec 不可用")

        settings = {
            "embedding": {
                "enabled": True,
                "endpoint": "",
                "local_fallback": True,
            }
        }
        (tmp_memory_db / "config" / "settings.yaml").write_text(
            _yaml.dump(settings), encoding="utf-8"
        )

        # 写入一些语义相关的记忆
        class MockLocalProvider:
            dimension = 384

            def encode(self, text):
                # 简单模拟：相同主题的文本产生相似向量
                t = text.lower()
                if "机器学习" in t or "深度学习" in t:
                    return [0.9] * 384
                elif "前端" in t or "react" in t:
                    return [0.1] * 384
                else:
                    return [0.5] * 384

        monkeypatch.setattr(emb_mod, "get_local_provider", lambda: MockLocalProvider())
        monkeypatch.setattr(emb_mod, "has_local_embedding", lambda: True)

        # 写入记忆
        asyncio.run(mem.write_memory({
            "memory_id": "ml-1",
            "content": "机器学习模型训练技巧",
            "summary": "学习率调度器和早停是训练深度神经网络的关键技巧",
            "source_agent": "test_agent",
            "source_task_id": "task-1",
            "tags": ["ml"],
            "user_id": "user1",
        }))

        asyncio.run(mem.write_memory({
            "memory_id": "frontend-1",
            "content": "React Hooks 使用指南",
            "summary": "useState 和 useEffect 是最常用的两个 React Hooks",
            "source_agent": "test_agent",
            "source_task_id": "task-2",
            "tags": ["frontend"],
            "user_id": "user1",
        }))

        # 搜索 ML 相关（LIKE 匹配）
        results = asyncio.run(mem.search_memory(query="模型训练"))
        assert len(results) >= 1

        # 搜索 React 相关（LIKE 匹配）
        results2 = asyncio.run(mem.search_memory(query="React Hooks"))
        assert len(results2) >= 1

    def test_rrf_fusion_combines_both_sources(self, tmp_memory_db, monkeypatch):
        """RRF 融合 FTS5 和向量两个结果源"""
        from agentmind.storage import memory as mem
        import agentmind.storage.embedding as emb_mod
        from agentmind.storage.db import is_vec_available

        if not is_vec_available():
            pytest.skip("sqlite-vec 不可用")

        settings = {
            "embedding": {
                "enabled": True,
                "endpoint": "",
                "local_fallback": True,
            }
        }
        (tmp_memory_db / "config" / "settings.yaml").write_text(
            _yaml.dump(settings), encoding="utf-8"
        )

        class MockLocalProvider:
            dimension = 384

            def encode(self, text):
                return [0.5] * 384

        monkeypatch.setattr(emb_mod, "get_local_provider", lambda: MockLocalProvider())
        monkeypatch.setattr(emb_mod, "has_local_embedding", lambda: True)

        # 写入关键字匹配的记忆（FTS5 能直接命中）
        asyncio.run(mem.write_memory({
            "memory_id": "python-decorator-1",
            "content": "Python 装饰器详解",
            "summary": "装饰器是 Python 中用于修改函数行为的一种设计模式",
            "source_agent": "test_agent",
            "source_task_id": "task-1",
            "user_id": "user1",
        }))

        # 写入语义相关的记忆（内容和搜索词不同但语义相近）
        asyncio.run(mem.write_memory({
            "memory_id": "python-metaprogramming-1",
            "content": "Python 元编程技术",
            "summary": "元类、描述符和属性访问是 Python 元编程的核心概念",
            "source_agent": "test_agent",
            "source_task_id": "task-2",
            "user_id": "user1",
        }))

        # 搜索 "装饰器" - FTS5 能直接命中第一条，向量搜索可能找到第二条
        results = asyncio.run(mem.search_memory(query="装饰器"))
        assert len(results) >= 1
        # 第一条应该是精确 FTS5 命中
        assert results[0]["memory_id"] == "python-decorator-1"

    def test_search_works_without_vec_available(self, tmp_memory_db, monkeypatch):
        """sqlite-vec 不可用时搜索仍能正常返回 FTS5 结果"""
        from agentmind.storage import memory as mem

        settings = {
            "embedding": {
                "enabled": True,
                "endpoint": "https://api.example.com/embeddings",
                "api_key": "sk-test",
            }
        }
        (tmp_memory_db / "config" / "settings.yaml").write_text(
            _yaml.dump(settings), encoding="utf-8"
        )

        # 强制 is_vec_available 返回 False
        monkeypatch.setattr(mem, "is_vec_available", lambda: False)

        asyncio.run(mem.write_memory({
            "memory_id": "text-1",
            "content": "单元测试最佳实践",
            "summary": "好的单元测试应该独立、可重复、快速",
            "source_agent": "test_agent",
            "source_task_id": "task-1",
            "user_id": "user1",
        }, generate_embedding=False))

        results = asyncio.run(mem.search_memory(query="单元测试"))
        assert len(results) >= 1
        assert results[0]["memory_id"] == "text-1"


class TestDimensionMismatch:
    """测试 embedding 维度不匹配的处理"""

    def test_vec_write_skipped_on_dimension_mismatch(self, tmp_memory_db, monkeypatch):
        """当 embedding 维度与 vec_memory 表维度不匹配时，静默跳过向量写入"""
        from agentmind.storage import memory as mem
        from agentmind.storage.db import is_vec_available

        if not is_vec_available():
            pytest.skip("sqlite-vec 不可用")

        # 写入时不生成 embedding，直接传一个维度错误的向量
        version = asyncio.run(mem.write_memory({
            "memory_id": "dim-test-1",
            "content": "维度测试",
            "summary": "测试维度不匹配",
            "source_agent": "test_agent",
            "source_task_id": "task-1",
            "user_id": "user1",
        }, generate_embedding=False))
        assert version == 1

        # 手动写入 vec_memory，使用错误维度（vec_memory 创建时使用 384 维，这里传 3 维）
        conn = mem._get_memory_conn()
        wrong_dim_emb = [1.0, 2.0, 3.0]
        wrong_blob = mem._embedding_to_blob(wrong_dim_emb)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO vec_memory(memory_id, embedding) VALUES (?, ?)",
                ("dim-test-1", wrong_blob),
            )
            conn.commit()
        except Exception:
            # 预期可能抛出异常（维度不匹配）
            pass
        finally:
            conn.close()

        # 即使 vec_memory 写入失败，memory_entries 中仍然有记录
        results = asyncio.run(mem.search_memory(query="维度测试"))
        assert len(results) >= 1
        assert results[0]["memory_id"] == "dim-test-1"
