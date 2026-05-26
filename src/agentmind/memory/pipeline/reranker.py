"""Reranker — bge-reranker-v2-m3 交叉编码器重排，可选，懒加载，默认关闭"""

import logging

from agentmind.memory.types import SearchResult

logger = logging.getLogger("agentmind")


class Reranker:
    """Cross-encoder reranker。模型不可用时静默透传。"""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        self._model_name = model_name
        self._model = None
        self._available = None  # None = 未检测，True/False = 已检测

    async def rerank(
        self, query: str, candidates: list[SearchResult], top_k: int = 10
    ) -> list[SearchResult]:
        if not candidates or len(candidates) <= 1:
            return candidates

        if not self._ensure_model():
            return candidates[:top_k]

        try:
            import asyncio
            pairs = [[query, c.entry.content[:500]] for c in candidates]
            scores = await asyncio.to_thread(
                self._model.compute_score, pairs, normalize=True
            )
            if not scores:
                return candidates[:top_k]

            for c, s in zip(candidates, scores):
                c.score = float(s)
            candidates.sort(key=lambda x: x.score, reverse=True)
            return candidates[:top_k]
        except Exception as e:
            logger.debug("Reranker 重排失败: %s", e)
            return candidates[:top_k]

    def _ensure_model(self) -> bool:
        if self._available is False:
            return False
        if self._model is not None:
            return True

        try:
            from FlagEmbedding import FlagReranker
            self._model = FlagReranker(self._model_name, use_fp16=True)
            self._available = True
            logger.info("Reranker 模型加载完成: %s", self._model_name)
            return True
        except ImportError:
            logger.debug("FlagEmbedding 未安装，Reranker 不可用")
            self._available = False
            return False
        except Exception as e:
            logger.debug("Reranker 模型加载失败: %s", e)
            self._available = False
            return False
