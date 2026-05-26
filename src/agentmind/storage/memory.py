"""共享记忆引擎 — 写入、混合检索（FTS5 + 向量）、统计、清理"""

import asyncio
import json
import logging
import sqlite3
import struct
from datetime import datetime, timezone

import httpx
import yaml

from agentmind.storage.db import CONFIG_DIR, DATA_DIR, _try_load_sqlite_vec, is_vec_available
from agentmind.storage.embedding import get_local_provider, has_local_embedding

logger = logging.getLogger("agentmind")

_EMBEDDING_SEMAPHORE = asyncio.Semaphore(3)


def _load_settings() -> dict:
    """读取 settings.yaml 配置"""
    settings_path = CONFIG_DIR / "settings.yaml"
    if not settings_path.exists():
        return {}
    try:
        return yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _get_agent_credibility(agent_id: str) -> float:
    """从 agents.yaml 读取 Agent 可信度，未知返回 0.5"""
    if not agent_id:
        return 0.5
    agents_path = CONFIG_DIR / "agents.yaml"
    if not agents_path.exists():
        return 0.5
    try:
        data = yaml.safe_load(agents_path.read_text(encoding="utf-8")) or {}
        for a in data.get("agents", []):
            if isinstance(a, dict) and a.get("id") == agent_id:
                return float(a.get("config", {}).get("credibility", 0.5))
    except Exception:
        pass
    return 0.5


def _get_memory_conn():
    conn = sqlite3.connect(str(DATA_DIR / "memory.db"), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    # 加载 sqlite-vec 扩展，使 vec_distance_cosine 等函数可用
    if is_vec_available():
        try:
            vec = _try_load_sqlite_vec()
            if vec is not None:
                conn.enable_load_extension(True)
                vec.load(conn)
        except Exception:
            pass
    return conn


def _now_sqlite() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ========== Embedding 生成 ==========

def _embedding_to_blob(embedding: list[float]) -> bytes:
    return struct.pack(f"{len(embedding)}f", *embedding)



async def _generate_embedding(text: str) -> list[float] | None:
    """调用 embedding API 生成向量，失败时降级到本地模型"""
    settings = _load_settings()
    cfg = settings.get("embedding", {})
    if not cfg.get("enabled"):
        return None

    # 先尝试外部 API
    if cfg.get("endpoint"):
        async with _EMBEDDING_SEMAPHORE:
            try:
                async with httpx.AsyncClient(timeout=cfg.get("timeout_seconds", 10)) as client:
                    resp = await client.post(
                        cfg["endpoint"],
                        headers={
                            "Authorization": f"Bearer {cfg.get('api_key', '')}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": cfg.get("model", "text-embedding-3-small"),
                            "input": text[:8000],
                        },
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        emb = data.get("data", [{}])[0].get("embedding")
                        if emb:
                            return emb
            except Exception as e:
                logger.debug("外部 embedding API 失败: %s", e)

    # 降级到本地模型
    if cfg.get("local_fallback", True):
        provider = get_local_provider()
        if provider:
            try:
                return await asyncio.to_thread(provider.encode, text[:8000])
            except Exception as e:
                logger.debug("本地 embedding 生成失败: %s", e)

    return None


# ========== 写入 ==========


def _find_similar_conflicts(conn, embedding: list[float], current_memory_id: str,
                            threshold: float) -> list[dict] | None:
    """用向量相似度搜索语义冲突的已有记忆，返回相似度 > threshold 的匹配列表"""
    if not embedding or not is_vec_available():
        return None

    blob = _embedding_to_blob(embedding)
    try:
        rows = conn.execute(
            """SELECT m.memory_id, m.source_agent, m.content, m.access_level,
                      vec_distance_cosine(v.embedding, ?) AS distance
               FROM vec_memory v
               JOIN memory_entries m ON v.memory_id = m.memory_id
               WHERE v.memory_id != ? AND m.access_level = 'shared'
               ORDER BY distance ASC LIMIT 3""",
            (blob, current_memory_id),
        ).fetchall()
    except Exception:
        return None

    matches = []
    for r in rows:
        similarity = 1.0 - r["distance"]
        if similarity >= threshold:
            matches.append({
                "memory_id": r["memory_id"],
                "source_agent": r["source_agent"],
                "content": r["content"][:200],
                "similarity": round(similarity, 3),
            })
    return matches if matches else None


def _write_memory_sync(entry: dict, embedding: list[float] | None = None):
    conn = _get_memory_conn()

    # 容量检查：超过阈值时 LRU 淘汰
    settings = _load_settings()
    max_entries = settings.get("memory", {}).get("max_entries", 10000)
    total = conn.execute("SELECT COUNT(*) as cnt FROM memory_entries").fetchone()["cnt"]
    if total >= max_entries:
        evict_count = max(1, int(total * 0.1))
        conn.execute(
            """DELETE FROM memory_entries WHERE memory_id IN (
                SELECT memory_id FROM memory_entries ORDER BY created_at ASC LIMIT ?
            )""",
            (evict_count,),
        )
        try:
            conn.execute(
                "DELETE FROM memory_fts WHERE memory_id NOT IN (SELECT memory_id FROM memory_entries)"
            )
        except Exception:
            pass
        if is_vec_available():
            try:
                conn.execute(
                    "DELETE FROM vec_memory WHERE memory_id NOT IN (SELECT memory_id FROM memory_entries)"
                )
            except Exception:
                pass
        logger.info("LRU 淘汰：%d 条", evict_count)

    # 保存原始 memory_id（冲突解决可能会修改 entry["memory_id"]）
    original_memory_id = entry["memory_id"]

    existing = conn.execute(
        "SELECT version, created_at, source_agent FROM memory_entries WHERE memory_id=?",
        (original_memory_id,),
    ).fetchone()
    version = (existing["version"] + 1) if existing else 1
    existing_created = existing["created_at"] if existing else None

    # 冲突检测：同 memory_id 已存在时比较可信度
    resolve_note = ""
    if existing:
        old_agent = existing["source_agent"]
        new_agent = entry.get("source_agent", "")
        old_cred = _get_agent_credibility(old_agent)
        new_cred = _get_agent_credibility(new_agent)
        if new_cred < old_cred:
            entry["access_level"] = "private"
            entry["memory_id"] = f"{original_memory_id}/v{version}"
            resolve_note = "conflict:new_lower_credibility"
            logger.info("冲突解决：%s 可信度(%.1f) < %s(%.1f)，新记忆降级",
                        new_agent or "?", new_cred, old_agent or "?", old_cred)

    # 语义冲突检测：用向量搜索发现不同 memory_id 但内容高度相似的记忆
    if not resolve_note and embedding:
        settings = _load_settings()
        mem_cfg = settings.get("memory", {})
        if mem_cfg.get("conflict_check_enabled", True):
            threshold = mem_cfg.get("conflict_similarity_threshold", 0.85)
            similar = _find_similar_conflicts(conn, embedding, original_memory_id, threshold)
            if similar:
                new_agent = entry.get("source_agent", "")
                new_cred = _get_agent_credibility(new_agent)
                for s in similar:
                    old_cred = _get_agent_credibility(s["source_agent"])
                    if new_cred < old_cred:
                        entry["access_level"] = "private"
                        resolve_note = f"conflict:semantic_similar({s['memory_id']},sim={s['similarity']})"
                        logger.info("语义冲突：%s 可信度(%.1f) < %s(%.1f)，相似度 %.2f，新记忆降级",
                                    new_agent or "?", new_cred, s["source_agent"] or "?", old_cred, s["similarity"])
                        break

    entry.setdefault("access_level", "shared")
    entry.setdefault("tags", [])
    entry.setdefault("user_id", "")
    entry["version"] = version
    if resolve_note:
        tags = entry.get("tags", [])
        if isinstance(tags, list):
            tags.append(resolve_note)
            entry["tags"] = tags
    created_at = entry.get("created_at") or existing_created or _now_sqlite()

    tags_json = json.dumps(entry.get("tags", [])) if isinstance(entry.get("tags"), list) else entry.get("tags", "[]")
    embedding_blob = _embedding_to_blob(embedding) if embedding else None

    # 更新时先删 FTS5 旧条目（使用原始 memory_id）
    if existing:
        try:
            conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (original_memory_id,))
        except Exception:
            pass

    conn.execute(
        """INSERT OR REPLACE INTO memory_entries
           (memory_id, content, summary, source_agent, source_task_id,
            created_at, access_level, tags, version, user_id, embedding)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entry["memory_id"],
            entry.get("content", ""),
            entry.get("summary", ""),
            entry.get("source_agent", ""),
            entry.get("source_task_id", ""),
            created_at,
            entry["access_level"],
            tags_json,
            version,
            entry.get("user_id", ""),
            embedding_blob,
        ),
    )

    # 手动同步 FTS5
    try:
        conn.execute(
            "INSERT INTO memory_fts(memory_id, content, summary, tags) VALUES (?, ?, ?, ?)",
            (entry["memory_id"], entry.get("content", ""), entry.get("summary", ""), tags_json),
        )
    except Exception:
        pass

    # 同步写入 vec_memory 向量索引
    if embedding_blob and is_vec_available():
        try:
            conn.execute(
                "INSERT OR REPLACE INTO vec_memory(memory_id, embedding) VALUES (?, ?)",
                (entry["memory_id"], embedding_blob),
            )
        except Exception:
            pass

    conn.commit()
    conn.close()
    return version


def _use_v4_memory_store() -> bool:
    """检查是否启用 v4 MemoryService 作为统一入口。"""
    try:
        import yaml
        from agentmind.storage.db import CONFIG_DIR
        path = CONFIG_DIR / "settings.yaml"
        if not path.exists():
            return False
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data.get("memory", {}).get("v4_write_enabled", False)
    except Exception:
        return False


async def write_memory(entry: dict, generate_embedding: bool = True) -> int:
    """写入记忆（LWW），可选异步生成 embedding。v4 开启时委托到 MemoryService。"""
    if _use_v4_memory_store():
        from agentmind.memory.service import MemoryService
        user_id = entry.get("user_id", "")
        return await MemoryService().write_memory(entry, user_id=user_id)

    emb = None
    if generate_embedding:
        settings = _load_settings()
        if settings.get("embedding", {}).get("enabled"):
            cfg = settings.get("embedding", {})
            has_source = bool(cfg.get("endpoint")) or has_local_embedding()
            if has_source:
                text = (entry.get("content", "") + " " + entry.get("summary", ""))[:8000]
                emb = await _generate_embedding(text)
    return await asyncio.to_thread(_write_memory_sync, entry, emb)


# ========== 混合检索 ==========

_EMBED_CACHE: dict[str, list[float]] = {}
_EMBED_CACHE_MAX = 64


def _search_memory_like(query: str, user_id: str | None, source_agent: str | None,
                       access_levels: list[str] | None, tags: list[str] | None,
                       limit: int) -> list[dict]:
    """LIKE 关键词搜索（稳定基础层）"""
    conn = _get_memory_conn()
    sql = "SELECT * FROM memory_entries WHERE 1=1"
    params = []

    if query:
        sql += " AND (content LIKE ? OR summary LIKE ?)"
        like = f"%{query}%"
        params.extend([like, like])

    if user_id:
        sql += " AND user_id = ?"
        params.append(user_id)

    if source_agent:
        sql += " AND source_agent = ?"
        params.append(source_agent)

    if access_levels:
        placeholders = ",".join("?" for _ in access_levels)
        sql += f" AND access_level IN ({placeholders})"
        params.extend(access_levels)

    sql_limit = max(1, min(limit if not tags else limit * 3, 500))
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(sql_limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    results = []
    for r in rows:
        d = dict(r)
        try:
            d["tags"] = json.loads(d.get("tags", "[]"))
        except (json.JSONDecodeError, TypeError):
            d["tags"] = []
        if "embedding" in d:
            d.pop("embedding", None)
        results.append(d)

    if tags:
        tag_set = set(tags)
        results = [r for r in results if tag_set & set(r.get("tags", []))]

    return results[:limit]


def _fts5_search(query: str, user_id: str | None, source_agent: str | None,
                 access_levels: list[str] | None, limit: int) -> list[dict]:
    """FTS5 全文搜索（增强层，查询词转义后 MATCH）"""
    conn = _get_memory_conn()
    try:
        safe_query = query.replace('"', '').replace("'", '').strip()
        if not safe_query:
            return []

        try:
            rows = conn.execute(
                """SELECT m.*, rank FROM memory_entries m
                   JOIN memory_fts f ON f.memory_id = m.memory_id
                   WHERE memory_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (safe_query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        results = []
        for r in rows:
            d = dict(r)
            d.pop("rank", None)
            d.pop("embedding", None)
            try:
                d["tags"] = json.loads(d.get("tags", "[]"))
            except (json.JSONDecodeError, TypeError):
                d["tags"] = []
            results.append(d)

        # Python 侧过滤（SQLite 侧无对应索引，保留 Python 过滤）
        if user_id:
            results = [r for r in results if r.get("user_id") == user_id]
        if source_agent:
            results = [r for r in results if r.get("source_agent") == source_agent]
        if access_levels:
            results = [r for r in results if r.get("access_level") in access_levels]

        return results
    finally:
        conn.close()


def _search_memory_sync(
    query: str = "",
    user_id: str = None,
    source_agent: str = None,
    tags: list[str] = None,
    access_levels: list[str] = None,
    limit: int = 10,
) -> list[dict]:
    """混合检索：FTS5 + 向量语义（RRF 融合），FTS5 不可用时降级 LIKE"""
    candidate_limit = limit * 2

    # 尝试 FTS5
    fts_results = _fts5_search(query, user_id, source_agent, access_levels, candidate_limit)

    # FTS5 无结果时降级 LIKE
    if not fts_results:
        return _search_memory_like(query, user_id, source_agent, access_levels, tags, limit)

    # 向量检索
    settings = _load_settings()
    vec_enabled = (
        settings.get("embedding", {}).get("enabled", False)
        and is_vec_available()
        and (bool(settings.get("embedding", {}).get("endpoint")) or has_local_embedding())
    )
    vec_results: list[dict] = []
    if vec_enabled and query:
        emb = await_or_sync_embedding(query, settings)
        if emb:
            vec_results = _vector_search(emb, user_id, source_agent, access_levels, candidate_limit)

    # 融合
    if vec_results:
        results = _rrf_fusion(fts_results, vec_results)
    else:
        results = fts_results

    # tags 过滤
    if tags:
        tag_set = set(tags)
        results = [r for r in results if tag_set & set(r.get("tags", []))]

    return results[:limit]


def _cache_embedding(query: str, emb: list[float]) -> list[float]:
    """缓存 embedding 结果，LRU 淘汰"""
    _EMBED_CACHE[query] = emb
    if len(_EMBED_CACHE) > _EMBED_CACHE_MAX:
        oldest = next(iter(_EMBED_CACHE))
        del _EMBED_CACHE[oldest]
    return emb


def await_or_sync_embedding(query: str, settings: dict) -> list[float] | None:
    """同步获取 embedding（在 asyncio.to_thread 线程中调用），外部 API 失败时降级到本地"""
    if query in _EMBED_CACHE:
        return _EMBED_CACHE[query]

    cfg = settings.get("embedding", {})
    text = query[:8000]

    # 先尝试外部 API
    if cfg.get("endpoint"):
        try:
            import requests as _sync_req

            resp = _sync_req.post(
                cfg["endpoint"],
                headers={
                    "Authorization": f"Bearer {cfg.get('api_key', '')}",
                    "Content-Type": "application/json",
                },
                json={"model": cfg.get("model", "text-embedding-3-small"), "input": text},
                timeout=cfg.get("timeout_seconds", 10),
            )
            if resp.status_code == 200:
                data = resp.json()
                emb = data.get("data", [{}])[0].get("embedding")
                if emb:
                    return _cache_embedding(query, emb)
        except Exception:
            pass

    # 降级到本地模型
    if cfg.get("local_fallback", True):
        provider = get_local_provider()
        if provider:
            try:
                emb = provider.encode(text)
                if emb:
                    return _cache_embedding(query, emb)
            except Exception:
                pass

    return None


def _vector_search(query_embedding: list[float], user_id: str | None,
                   source_agent: str | None, access_levels: list[str] | None,
                   limit: int) -> list[dict]:
    """向量相似度搜索（需要 sqlite-vec 已加载）"""
    conn = _get_memory_conn()
    blob = _embedding_to_blob(query_embedding)

    try:
        rows = conn.execute(
            """SELECT m.*, vec_distance_cosine(vec_memory.embedding, ?) AS distance
               FROM memory_entries m
               JOIN vec_memory ON vec_memory.memory_id = m.memory_id
               WHERE vec_memory.embedding MATCH ?
               ORDER BY distance LIMIT ?""",
            (blob, blob, limit),
        ).fetchall()
    except Exception:
        conn.close()
        return []

    results = []
    for r in rows:
        d = dict(r)
        d["_distance"] = r["distance"] if "distance" in r.keys() else 1.0
        d.pop("embedding", None)
        try:
            d["tags"] = json.loads(d.get("tags", "[]"))
        except (json.JSONDecodeError, TypeError):
            d["tags"] = []
        results.append(d)

    conn.close()

    if user_id:
        results = [r for r in results if r.get("user_id") == user_id]
    if source_agent:
        results = [r for r in results if r.get("source_agent") == source_agent]
    if access_levels:
        results = [r for r in results if r.get("access_level") in access_levels]

    return results


def _rrf_fusion(fts_results: list[dict], vec_results: list[dict], k: int = 60) -> list[dict]:
    """RRF 融合两路检索结果"""
    scores: dict[str, tuple[float, dict]] = {}
    for rank, item in enumerate(fts_results):
        mid = item["memory_id"]
        scores[mid] = (1.0 / (k + rank + 1), item)
    for rank, item in enumerate(vec_results):
        mid = item["memory_id"]
        rrf = 1.0 / (k + rank + 1)
        if mid in scores:
            scores[mid] = (scores[mid][0] + rrf, scores[mid][1])
        else:
            scores[mid] = (rrf, item)

    sorted_items = sorted(scores.values(), key=lambda x: x[0], reverse=True)
    return [item for _, item in sorted_items]


async def search_memory(
    query: str = "",
    user_id: str = None,
    source_agent: str = None,
    tags: list[str] = None,
    access_levels: list[str] = None,
    limit: int = 10,
) -> list[dict]:
    """混合检索记忆：FTS5 + 向量语义（RRF 融合）。v4 开启时委托到 MemoryService。"""
    if _use_v4_memory_store():
        from agentmind.memory.service import MemoryService
        return await MemoryService().search_memory(
            query=query, user_id=user_id or "",
            source_agent=source_agent or "",
            tags=tags, access_levels=access_levels,
            limit=limit,
        )

    results = await asyncio.to_thread(
        _search_memory_sync, query, user_id, source_agent, tags, access_levels, limit
    )
    # 更新访问时间（热度追踪，异步避免阻塞事件循环）
    if results:
        await asyncio.to_thread(_touch_memory_access, [r["memory_id"] for r in results])
    return results


def _touch_memory_access(memory_ids: list[str]):
    """批量更新 last_accessed_at"""
    conn = _get_memory_conn()
    now = _now_sqlite()
    for mid in memory_ids:
        try:
            conn.execute(
                "UPDATE memory_entries SET last_accessed_at = ? WHERE memory_id = ?",
                (now, mid),
            )
        except Exception:
            pass
    conn.commit()
    conn.close()


# ========== 统计 ==========

def _get_memory_stats_sync() -> dict:
    conn = _get_memory_conn()
    total = conn.execute("SELECT COUNT(*) as cnt FROM memory_entries").fetchone()["cnt"]

    by_source = {}
    for r in conn.execute(
        "SELECT source_agent, COUNT(*) as cnt FROM memory_entries GROUP BY source_agent"
    ).fetchall():
        by_source[r["source_agent"]] = r["cnt"]

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
            with_embedding = conn.execute(
                "SELECT COUNT(*) as cnt FROM vec_memory"
            ).fetchone()["cnt"]
        except Exception:
            pass

    # 热度统计
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

    conn.close()
    return {
        "total": total,
        "by_source_agent": by_source,
        "by_access_level": by_access,
        "by_heat": {"hot": hot, "warm": warm, "cold": cold},
        "latest_at": latest["created_at"] if latest else None,
        "vector_search_enabled": vec_enabled,
        "with_embedding": with_embedding,
    }


async def get_memory_stats() -> dict:
    if _use_v4_memory_store():
        from agentmind.memory.service import MemoryService
        return await MemoryService().get_memory_stats()
    return await asyncio.to_thread(_get_memory_stats_sync)


# ========== 清理 ==========

def _cleanup_memory_sync(retention_days: int = 30) -> int:
    conn = _get_memory_conn()
    now = _now_sqlite()

    # 先获取待删除的 memory_id 列表
    rows = conn.execute(
        "SELECT memory_id FROM memory_entries WHERE created_at <= datetime(?, ?)",
        (now, f"-{retention_days} days"),
    ).fetchall()

    if not rows:
        conn.close()
        return 0

    memory_ids = [r["memory_id"] for r in rows]

    # 从主表删除
    conn.execute(
        "DELETE FROM memory_entries WHERE created_at <= datetime(?, ?)",
        (now, f"-{retention_days} days"),
    )

    # 同步清理 FTS5
    for mid in memory_ids:
        try:
            conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (mid,))
        except Exception:
            pass

    # 同步清理向量索引
    if is_vec_available():
        for mid in memory_ids:
            try:
                conn.execute("DELETE FROM vec_memory WHERE memory_id = ?", (mid,))
            except Exception:
                pass

    deleted = len(memory_ids)
    conn.commit()
    conn.close()
    if deleted:
        logger.info("记忆清理：删除了 %d 条超过 %d 天的记忆", deleted, retention_days)
    return deleted


async def cleanup_memory(retention_days: int = 30) -> int:
    """清理超过 retention_days 天的记忆，返回删除数"""
    if _use_v4_memory_store():
        from agentmind.memory.service import MemoryService
        return await MemoryService().cleanup_memory(retention_days=retention_days)
    return await asyncio.to_thread(_cleanup_memory_sync, retention_days)
