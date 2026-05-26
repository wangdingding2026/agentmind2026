"""SQLite 实现 IMemoryStore 接口 — v4 记忆存储"""

import asyncio
import json
import logging
import sqlite3
import struct
from datetime import datetime, timezone

from agentmind.memory.repository import IMemoryStore
from agentmind.memory.types import MemoryEntry, MemoryType, SearchQuery, SearchResult
from agentmind.storage.db import DATA_DIR, _try_load_sqlite_vec, is_vec_available

logger = logging.getLogger("agentmind")


def _has_cjk(text: str) -> bool:
    """检查文本是否包含中日韩字符"""
    for ch in text:
        cp = ord(ch)
        if (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or
            0x3040 <= cp <= 0x309F or 0x30A0 <= cp <= 0x30FF or
            0xAC00 <= cp <= 0xD7AF):
            return True
    return False


def _now_sqlite() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _embedding_to_blob(embedding: list[float]) -> bytes:
    return struct.pack(f"{len(embedding)}f", *embedding)



class SqliteMemoryStore(IMemoryStore):
    """SQLite 实现 IMemoryStore。"""

    def __init__(self, db_path: str = ""):
        self._db_path = db_path or str(DATA_DIR / "memory.db")

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        if is_vec_available():
            try:
                vec = _try_load_sqlite_vec()
                if vec is not None:
                    conn.enable_load_extension(True)
                    vec.load(conn)
            except Exception:
                pass
        return conn

    # ── 写入 ──

    async def insert(self, entry: MemoryEntry) -> str:
        return await asyncio.to_thread(self._insert_sync, entry)

    async def update(self, entry: MemoryEntry) -> str:
        return await asyncio.to_thread(self._update_sync, entry)

    async def batch_insert(self, entries: list[MemoryEntry]) -> list[str]:
        return await asyncio.to_thread(self._batch_insert_sync, entries)

    def _insert_sync(self, entry: MemoryEntry) -> str:
        conn = self._get_conn()
        try:
            now = _now_sqlite()
            if not entry.created_at:
                entry.created_at = now
            tags_json = json.dumps(entry.tags) if entry.tags else "[]"

            conn.execute(
                """INSERT OR REPLACE INTO memory_entries
                   (memory_id, content, summary, source_agent, source_task_id,
                    created_at, access_level, tags, version, user_id,
                    memory_type, conversation_id, importance, content_hash,
                    embedding_model, embedding_version, parent_id, distilled, expire_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.memory_id, entry.content, entry.summary,
                    entry.source_agent, entry.source_task_id,
                    entry.created_at, entry.access_level, tags_json, entry.version, entry.user_id,
                    entry.memory_type.value, entry.conversation_id, entry.importance, entry.content_hash,
                    entry.embedding_model, entry.embedding_version, entry.parent_id, entry.distilled, entry.expire_at,
                ),
            )

            # FTS5 同步（先删后插，FTS 表不支持按 rowid REPLACE）
            try:
                conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (entry.memory_id,))
                conn.execute(
                    "INSERT INTO memory_fts(memory_id, content, summary, tags) VALUES (?, ?, ?, ?)",
                    (entry.memory_id, entry.content, entry.summary, tags_json),
                )
            except Exception:
                pass

            conn.commit()
            return entry.memory_id
        finally:
            conn.close()

    def _update_sync(self, entry: MemoryEntry) -> str:
        conn = self._get_conn()
        try:
            tags_json = json.dumps(entry.tags) if entry.tags else "[]"

            conn.execute(
                """UPDATE memory_entries SET
                   content=?, summary=?, source_agent=?, access_level=?, tags=?, version=version+1,
                   memory_type=?, conversation_id=?, importance=?, content_hash=?,
                   embedding_model=?, embedding_version=?, parent_id=?, distilled=?, expire_at=?,
                   last_accessed_at=?
                   WHERE memory_id=?""",
                (
                    entry.content, entry.summary, entry.source_agent, entry.access_level, tags_json,
                    entry.memory_type.value, entry.conversation_id, entry.importance, entry.content_hash,
                    entry.embedding_model, entry.embedding_version, entry.parent_id, entry.distilled, entry.expire_at,
                    _now_sqlite(), entry.memory_id,
                ),
            )

            # FTS5 同步
            try:
                conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (entry.memory_id,))
                conn.execute(
                    "INSERT INTO memory_fts(memory_id, content, summary, tags) VALUES (?, ?, ?, ?)",
                    (entry.memory_id, entry.content, entry.summary, tags_json),
                )
            except Exception:
                pass

            conn.commit()
            return entry.memory_id
        finally:
            conn.close()

    def _batch_insert_sync(self, entries: list[MemoryEntry]) -> list[str]:
        if not entries:
            return []
        conn = self._get_conn()
        try:
            now = _now_sqlite()
            ids = []
            for entry in entries:
                if not entry.created_at:
                    entry.created_at = now
                tags_json = json.dumps(entry.tags) if entry.tags else "[]"
                try:
                    conn.execute(
                        """INSERT OR REPLACE INTO memory_entries
                           (memory_id, content, summary, source_agent, source_task_id,
                            created_at, access_level, tags, version, user_id,
                            memory_type, conversation_id, importance, content_hash,
                            embedding_model, embedding_version, parent_id, distilled, expire_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            entry.memory_id, entry.content, entry.summary,
                            entry.source_agent, entry.source_task_id,
                            entry.created_at, entry.access_level, tags_json, entry.version, entry.user_id,
                            entry.memory_type.value, entry.conversation_id, entry.importance, entry.content_hash,
                            entry.embedding_model, entry.embedding_version, entry.parent_id, entry.distilled, entry.expire_at,
                        ),
                    )
                    try:
                        conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (entry.memory_id,))
                        conn.execute(
                            "INSERT INTO memory_fts(memory_id, content, summary, tags) VALUES (?, ?, ?, ?)",
                            (entry.memory_id, entry.content, entry.summary, tags_json),
                        )
                    except Exception:
                        pass
                    ids.append(entry.memory_id)
                except Exception:
                    pass
            conn.commit()
            return ids
        finally:
            conn.close()

    # ── 检索 ──

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        return await asyncio.to_thread(self._search_sync, query)

    def _search_sync(self, query: SearchQuery) -> list[SearchResult]:
        conn = self._get_conn()
        graph_results = []
        try:
            # FTS5 主路
            results = self._fts5_search(conn, query)

            # FTS5 无结果时降级 LIKE
            if not results and query.query_text:
                results = self._like_search(conn, query)

            # LIKE 也无结果且含中文时，尝试 n-gram 分词降级
            if not results and query.query_text and _has_cjk(query.query_text):
                results = self._relaxed_like_search(conn, query)

            # 图 1-hop 扩展（从 FTS5 结果出发，查 memory_relations）
            if results and query.user_id:
                try:
                    graph_results = self._graph_1hop_search(conn, results, query.user_id, limit=10)
                except Exception:
                    pass

            # 向量检索增强
            vec_results = []
            if query.query_text and is_vec_available():
                vec_results = self._vec_search(conn, query)

            # RRF 融合（三路：FTS5 + vec + graph）
            if vec_results:
                results = self._rrf_fusion(results, vec_results)
            if graph_results:
                results = self._rrf_fusion(results, graph_results)

            # 信号加权（importance + recency + access_count）
            results = self._apply_signal_weights(results)

            return results[:query.limit]
        finally:
            conn.close()

    def _build_filter_clause(self, query: SearchQuery) -> tuple[str, list]:
        """构建用户/权限/类型/时间/标签过滤条件。返回 (sql_clause, params)。"""
        conditions = []
        params = []

        if query.user_id:
            conditions.append("user_id = ?")
            params.append(query.user_id)

        if query.access_levels:
            placeholders = ",".join("?" for _ in query.access_levels)
            conditions.append(f"access_level IN ({placeholders})")
            params.extend(query.access_levels)

        if query.memory_types:
            type_values = [mt.value for mt in query.memory_types]
            placeholders = ",".join("?" for _ in type_values)
            conditions.append(f"memory_type IN ({placeholders})")
            params.extend(type_values)

        if query.time_range_start:
            conditions.append("created_at >= ?")
            params.append(query.time_range_start)
        if query.time_range_end:
            conditions.append("created_at <= ?")
            params.append(query.time_range_end)

        if query.tags:
            tag_clauses = []
            for t in query.tags:
                tag_clauses.append("tags LIKE ?")
                params.append(f"%{t}%")
            conditions.append(f"({' OR '.join(tag_clauses)})")

        if query.conversation_id:
            conditions.append("conversation_id = ?")
            params.append(query.conversation_id)

        clause = (" AND " + " AND ".join(conditions)) if conditions else ""
        return clause, params

    def _fts5_search(self, conn, query: SearchQuery) -> list[SearchResult]:
        safe = query.query_text.replace('"', '').replace("'", '').strip()
        if not safe:
            return self._recent_results(conn, query)

        filter_clause, filter_params = self._build_filter_clause(query)
        try:
            sql = f"""SELECT m.*, rank FROM memory_entries m
                   JOIN memory_fts f ON f.memory_id = m.memory_id
                   WHERE memory_fts MATCH ?{filter_clause}
                   ORDER BY rank LIMIT ?"""
            rows = conn.execute(
                sql, [safe] + filter_params + [query.limit * 3],
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        return [self._row_to_result(r, route="fts5", rank=getattr(r, "rank", 0)) for r in rows]

    def _like_search(self, conn, query: SearchQuery) -> list[SearchResult]:
        like = f"%{query.query_text}%"
        filter_clause, filter_params = self._build_filter_clause(query)
        sql = f"""SELECT * FROM memory_entries
               WHERE (content LIKE ? OR summary LIKE ?){filter_clause}
               ORDER BY created_at DESC LIMIT ?"""
        rows = conn.execute(
            sql, [like, like] + filter_params + [query.limit * 2],
        ).fetchall()
        return [self._row_to_result(r, route="like") for r in rows]

    def _relaxed_like_search(self, conn, query: SearchQuery) -> list[SearchResult]:
        """中文分词降级 LIKE：将查询拆分为 2-3 字片段，OR 匹配"""
        text = query.query_text
        terms = []
        for i in range(len(text) - 1):
            terms.append(text[i:i + 2])
        for i in range(len(text) - 2):
            terms.append(text[i:i + 3])

        unique_terms = list(dict.fromkeys(terms))[:5]

        if not unique_terms:
            return []

        clauses = []
        params = []
        for t in unique_terms:
            clauses.append("(content LIKE ? OR summary LIKE ?)")
            like = f"%{t}%"
            params.extend([like, like])

        filter_clause, filter_params = self._build_filter_clause(query)
        sql = f"""SELECT * FROM memory_entries
               WHERE ({' OR '.join(clauses)}){filter_clause}
               ORDER BY created_at DESC LIMIT ?"""
        params.extend(filter_params)
        params.append(query.limit * 3)

        try:
            rows = conn.execute(sql, params).fetchall()
        except Exception:
            return []

        return [self._row_to_result(r, route="relaxed_like") for r in rows]

    def _recent_results(self, conn, query: SearchQuery) -> list[SearchResult]:
        filter_clause, filter_params = self._build_filter_clause(query)
        if filter_clause:
            sql = f"SELECT * FROM memory_entries WHERE 1=1{filter_clause} ORDER BY created_at DESC LIMIT ?"
            rows = conn.execute(sql, filter_params + [query.limit * 2]).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memory_entries ORDER BY created_at DESC LIMIT ?",
                (query.limit * 2,),
            ).fetchall()
        return [self._row_to_result(r, route="recent") for r in rows]

    def _vec_search(self, conn, query: SearchQuery) -> list[SearchResult]:
        """向量相似度搜索。自动选择最新版本的 vec_memory_v{N} 表，降级 vec_memory。"""
        vec_table = self._resolve_vec_table(conn)
        if not vec_table:
            return []

        emb = self._get_query_embedding(query.query_text)
        if not emb:
            return []

        blob = _embedding_to_blob(emb)
        try:
            rows = conn.execute(
                f"""SELECT m.*, vec_distance_cosine(v.embedding, ?) AS distance
                   FROM memory_entries m
                   JOIN {vec_table} v ON v.memory_id = m.memory_id
                   WHERE v.embedding MATCH ?
                   ORDER BY distance LIMIT ?""",
                (blob, blob, query.limit * 2),
            ).fetchall()
        except Exception:
            return []

        return [self._row_to_result(r, route="vector", score=1.0 - r["distance"]) for r in rows]

    def _resolve_vec_table(self, conn) -> str | None:
        """解析当前应使用的向量表：优先最新版本 vec_memory_v{N}，降级 vec_memory。"""
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'vec_memory%'"
            ).fetchall()
        except Exception:
            return None

        if not tables:
            return None

        # 收集版本号，选最大
        best_version = 0
        best_table = None
        import re
        for (name,) in tables:
            m = re.match(r'vec_memory_v(\d+)$', name)
            if m:
                v = int(m.group(1))
                if v > best_version:
                    best_version = v
                    best_table = name
            elif name == "vec_memory" and best_version == 0:
                best_table = "vec_memory"

        return best_table

    def _get_query_embedding(self, text: str) -> list[float] | None:
        """尝试获取 query 文本的 embedding（优先外部 API，降级本地模型）"""
        try:
            from agentmind.storage.memory import _load_settings, await_or_sync_embedding
            settings = _load_settings()
            return await_or_sync_embedding(text, settings)
        except Exception:
            return None

    def _rrf_fusion(
        self, fts_results: list[SearchResult], vec_results: list[SearchResult], k: int = 60
    ) -> list[SearchResult]:
        scores: dict[str, tuple[float, SearchResult]] = {}
        for rank, item in enumerate(fts_results):
            mid = item.entry.memory_id
            scores[mid] = (1.0 / (k + rank + 1), item)
        for rank, item in enumerate(vec_results):
            mid = item.entry.memory_id
            rrf = 1.0 / (k + rank + 1)
            if mid in scores:
                combined = scores[mid][0] + rrf
                scores[mid] = (combined, scores[mid][1])
            else:
                scores[mid] = (rrf, item)
        sorted_items = sorted(scores.values(), key=lambda x: x[0], reverse=True)
        for score, item in sorted_items:
            item.score = max(item.score, score)
        return [item for _, item in sorted_items]

    def _graph_1hop_search(
        self, conn, fts_results: list[SearchResult], user_id: str, limit: int = 10
    ) -> list[SearchResult]:
        """从 FTS5 结果出发，通过 memory_relations + entity 文本匹配做 1-hop 扩展。"""
        fts_ids = [r.entry.memory_id for r in fts_results[:10]]
        if not fts_ids:
            return []

        # 路 1：查 memory_relations 表的 memory_id join（head 或 tail）
        placeholders = ",".join("?" for _ in fts_ids)
        try:
            rel_rows = conn.execute(
                f"""SELECT DISTINCT head_memory_id, tail_memory_id, tail_entity FROM memory_relations
                   WHERE user_id=? AND (head_memory_id IN ({placeholders}) OR tail_memory_id IN ({placeholders}))
                   LIMIT ?""",
                [user_id] + fts_ids + fts_ids + [limit * 2],
            ).fetchall()
        except Exception:
            rel_rows = []

        linked_ids = set()
        entity_texts = set()
        for r in rel_rows:
            if r["head_memory_id"] and r["head_memory_id"] not in fts_ids:
                linked_ids.add(r["head_memory_id"])
            if r["tail_memory_id"] and r["tail_memory_id"] not in fts_ids:
                linked_ids.add(r["tail_memory_id"])
            # 收集 tail_entity 文本，用于路 2 的内容匹配
            if r["tail_entity"] and len(r["tail_entity"]) >= 2:
                entity_texts.add(r["tail_entity"])

        # 路 2：如果 memory_id join 没找到，通过 tail_entity 文本做内容 LIKE 匹配
        if not linked_ids and entity_texts:
            for entity in list(entity_texts)[:5]:
                like = f"%{entity}%"
                try:
                    rows = conn.execute(
                        """SELECT * FROM memory_entries
                           WHERE user_id=? AND (content LIKE ? OR summary LIKE ?)
                           AND memory_id NOT IN ({})
                           ORDER BY created_at DESC LIMIT ?""".format(
                            ",".join("?" for _ in fts_ids)
                        ),
                        [user_id, like, like] + fts_ids + [limit],
                    ).fetchall()
                    for r in rows:
                        linked_ids.add(r["memory_id"])
                except Exception:
                    pass

        if not linked_ids:
            return []

        linked_list = list(linked_ids)[:limit]
        lplaceholders = ",".join("?" for _ in linked_list)
        try:
            rows = conn.execute(
                f"SELECT * FROM memory_entries WHERE memory_id IN ({lplaceholders})",
                linked_list,
            ).fetchall()
        except Exception:
            return []

        return [self._row_to_result(r, route="graph") for r in rows]

    def _apply_signal_weights(self, results: list[SearchResult]) -> list[SearchResult]:
        """在 RRF 分数基础上叠加 importance + recency + access_count 信号加权。"""
        import math
        from datetime import datetime, timezone

        if not results:
            return results

        now = datetime.now(timezone.utc)
        for item in results:
            e = item.entry
            rrf = item.score if item.score > 0 else 0.01

            # recency: 越新越高
            age_days = 30.0
            if e.created_at:
                try:
                    created = datetime.strptime(e.created_at[:10], "%Y-%m-%d")
                    age_days = max(0, (now - created.replace(tzinfo=timezone.utc)).days)
                except (ValueError, TypeError):
                    pass
            recency = math.exp(-0.05 * age_days)

            # importance: 0-1
            importance = max(0.0, min(1.0, e.importance))

            # access_count: log scale
            access_count = max(0, e.version)  # version 粗略反映更新次数
            access_bonus = math.log(access_count + 1) / 10.0

            item.score = 0.5 * rrf + 0.2 * recency + 0.2 * importance + 0.1 * access_bonus

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def _row_to_result(self, row, route: str = "", score: float = 0.0, rank: int = 0) -> SearchResult:
        d = dict(row)
        d.pop("embedding", None)
        try:
            tags = json.loads(d.get("tags", "[]"))
        except (json.JSONDecodeError, TypeError):
            tags = []
        d["tags"] = tags

        memory_type = d.get("memory_type", "episodic")
        if isinstance(memory_type, str):
            try:
                memory_type = MemoryType(memory_type)
            except ValueError:
                memory_type = MemoryType.EPISODIC

        entry = MemoryEntry(
            memory_id=d.get("memory_id", ""),
            content=d.get("content", ""),
            summary=d.get("summary", ""),
            source_agent=d.get("source_agent", ""),
            source_task_id=d.get("source_task_id", ""),
            user_id=d.get("user_id", ""),
            memory_type=memory_type,
            conversation_id=d.get("conversation_id", ""),
            importance=float(d.get("importance", 0.5)),
            content_hash=d.get("content_hash", ""),
            embedding_model=d.get("embedding_model", ""),
            embedding_version=int(d.get("embedding_version", 1)),
            parent_id=d.get("parent_id", ""),
            distilled=int(d.get("distilled", 0)),
            expire_at=d.get("expire_at", ""),
            tags=tags,
            access_level=d.get("access_level", "shared"),
            version=int(d.get("version", 1)),
            created_at=d.get("created_at", ""),
            last_accessed_at=d.get("last_accessed_at", ""),
        )
        return SearchResult(entry=entry, score=score, route=route)

    # ── 删除 ──

    async def delete(self, memory_id: str) -> bool:
        return await asyncio.to_thread(self._delete_sync, memory_id)

    def _delete_sync(self, memory_id: str) -> bool:
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM memory_entries WHERE memory_id=?", (memory_id,))
            try:
                conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (memory_id,))
            except Exception:
                pass
            if is_vec_available():
                try:
                    conn.execute("DELETE FROM vec_memory WHERE memory_id=?", (memory_id,))
                except Exception:
                    pass
            conn.commit()
            return True
        finally:
            conn.close()

    # ── 查询 ──

    async def get(self, memory_id: str) -> MemoryEntry | None:
        return await asyncio.to_thread(self._get_sync, memory_id)

    def _get_sync(self, memory_id: str) -> MemoryEntry | None:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM memory_entries WHERE memory_id=?", (memory_id,)
            ).fetchone()
            if row is None:
                return None
            result = self._row_to_result(row, route="direct")
            return result.entry
        finally:
            conn.close()

    async def count(self, user_id: str = "") -> int:
        return await asyncio.to_thread(self._count_sync, user_id)

    def _count_sync(self, user_id: str = "") -> int:
        conn = self._get_conn()
        try:
            if user_id:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM memory_entries WHERE user_id=?", (user_id,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) as cnt FROM memory_entries").fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    async def get_stats(self) -> dict:
        return await asyncio.to_thread(self._get_stats_sync)

    def _get_stats_sync(self) -> dict:
        conn = self._get_conn()
        try:
            total = conn.execute("SELECT COUNT(*) as cnt FROM memory_entries").fetchone()["cnt"]

            by_source = {}
            for r in conn.execute(
                "SELECT source_agent, COUNT(*) as cnt FROM memory_entries GROUP BY source_agent"
            ).fetchall():
                by_source[r["source_agent"] or "unknown"] = r["cnt"]

            by_type = {}
            try:
                for r in conn.execute(
                    "SELECT memory_type, COUNT(*) as cnt FROM memory_entries GROUP BY memory_type"
                ).fetchall():
                    by_type[r["memory_type"] or "episodic"] = r["cnt"]
            except Exception:
                by_type = {"episodic": total}

            by_access = {}
            for r in conn.execute(
                "SELECT access_level, COUNT(*) as cnt FROM memory_entries GROUP BY access_level"
            ).fetchall():
                by_access[r["access_level"]] = r["cnt"]

            latest = conn.execute(
                "SELECT created_at FROM memory_entries ORDER BY created_at DESC LIMIT 1"
            ).fetchone()

            vec_enabled = is_vec_available()
            with_embedding = 0
            if vec_enabled:
                try:
                    with_embedding = conn.execute("SELECT COUNT(*) as cnt FROM vec_memory").fetchone()["cnt"]
                except Exception:
                    pass

            hot = conn.execute(
                "SELECT COUNT(*) as cnt FROM memory_entries"
                " WHERE last_accessed_at > datetime('now', '-7 days')"
            ).fetchone()["cnt"]
            warm = conn.execute(
                "SELECT COUNT(*) as cnt FROM memory_entries"
                " WHERE last_accessed_at > datetime('now', '-30 days')"
                " AND last_accessed_at <= datetime('now', '-7 days')"
            ).fetchone()["cnt"]
            cold = conn.execute(
                "SELECT COUNT(*) as cnt FROM memory_entries"
                " WHERE last_accessed_at IS NULL OR last_accessed_at <= datetime('now', '-30 days')"
            ).fetchone()["cnt"]

            return {
                "total": total,
                "by_source_agent": by_source,
                "by_type": by_type,
                "by_access_level": by_access,
                "by_heat": {"hot": hot, "warm": warm, "cold": cold},
                "latest_at": latest["created_at"] if latest else None,
                "vector_search_enabled": vec_enabled,
                "with_embedding": with_embedding,
            }
        finally:
            conn.close()
