"""Provider boundary for memory settings and embeddings."""

from __future__ import annotations

import asyncio
import logging
import struct

import httpx

from agentmind.services.config_service import ConfigService
from agentmind.storage.embedding import get_local_provider

logger = logging.getLogger("agentmind")

_EMBEDDING_SEMAPHORE = asyncio.Semaphore(3)
_EMBED_CACHE: dict[str, list[float]] = {}
_EMBED_CACHE_MAX = 512


def read_memory_settings() -> dict:
    try:
        return ConfigService().read_settings()
    except Exception:
        return {}


def read_agent_credibility(agent_id: str) -> float:
    if not agent_id:
        return 0.5
    try:
        data = ConfigService().read_agents()
        for item in data.get("agents", []):
            if isinstance(item, dict) and item.get("id") == agent_id:
                return float(item.get("config", {}).get("credibility", 0.5))
    except Exception:
        pass
    return 0.5


def embedding_to_blob(embedding: list[float]) -> bytes:
    return struct.pack(f"{len(embedding)}f", *embedding)


class MemoryEmbeddingProvider:
    async def generate_embedding(self, text: str) -> list[float]:
        settings = read_memory_settings()
        cfg = settings.get("embedding", {})
        if not cfg.get("enabled"):
            return []

        limited_text = text[:8000]
        if cfg.get("endpoint"):
            async with _EMBEDDING_SEMAPHORE:
                try:
                    async with httpx.AsyncClient(
                        timeout=cfg.get("timeout_seconds", 10)
                    ) as client:
                        resp = await client.post(
                            cfg["endpoint"],
                            headers={
                                "Authorization": f"Bearer {cfg.get('api_key', '')}",
                                "Content-Type": "application/json",
                            },
                            json={
                                "model": cfg.get("model", "text-embedding-3-small"),
                                "input": limited_text,
                            },
                        )
                    if resp.status_code == 200:
                        data = resp.json()
                        emb = data.get("data", [{}])[0].get("embedding")
                        if emb:
                            return emb
                except Exception as exc:
                    logger.debug("外部 embedding API 失败: %s", exc)

        if cfg.get("local_fallback", True):
            provider = get_local_provider()
            if provider:
                try:
                    return await asyncio.to_thread(provider.encode, limited_text)
                except Exception as exc:
                    logger.debug("本地 embedding 生成失败: %s", exc)

        return []


def generate_embedding_sync(text: str, settings: dict | None = None) -> list[float]:
    settings = settings if settings is not None else read_memory_settings()
    cfg = settings.get("embedding", {})
    if cfg.get("enabled") is False:
        return []

    cached = _EMBED_CACHE.get(text)
    if cached is not None:
        return cached

    limited_text = text[:8000]
    if cfg.get("endpoint"):
        try:
            with httpx.Client(timeout=cfg.get("timeout_seconds", 10)) as client:
                resp = client.post(
                    cfg["endpoint"],
                    headers={
                        "Authorization": f"Bearer {cfg.get('api_key', '')}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": cfg.get("model", "text-embedding-3-small"),
                        "input": limited_text,
                    },
                )
            if resp.status_code == 200:
                data = resp.json()
                emb = data.get("data", [{}])[0].get("embedding")
                if emb:
                    return _cache_embedding(text, emb)
        except Exception:
            pass

    if cfg.get("local_fallback", True):
        provider = get_local_provider()
        if provider:
            try:
                emb = provider.encode(limited_text)
                if emb:
                    return _cache_embedding(text, emb)
            except Exception:
                pass

    return []


def _cache_embedding(text: str, embedding: list[float]) -> list[float]:
    _EMBED_CACHE[text] = embedding
    if len(_EMBED_CACHE) > _EMBED_CACHE_MAX:
        oldest = next(iter(_EMBED_CACHE))
        del _EMBED_CACHE[oldest]
    return embedding
