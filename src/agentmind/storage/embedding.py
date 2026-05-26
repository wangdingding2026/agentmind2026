"""本地 embedding 提供者 — 离线语义向量生成

提供基于 sentence-transformers 的本地 embedding 模型，
作为外部 API 的降级方案，也支持完全不依赖外部 API 的独立运行。
"""

import logging
import threading
from typing import Optional

logger = logging.getLogger("agentmind")

_local_provider: Optional["LocalEmbeddingProvider"] = None
_local_lock = threading.Lock()


class LocalEmbeddingProvider:
    """基于 sentence-transformers 的本地 embedding 模型，懒加载"""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None
        self._dim = None

    @property
    def dimension(self) -> int:
        """返回模型输出的向量维度（触发懒加载）"""
        if self._dim is None:
            self._load()
        return self._dim

    def _load(self):
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer

        logger.info("加载本地 embedding 模型: %s", self.model_name)
        self._model = SentenceTransformer(self.model_name)
        self._dim = self._model.get_sentence_embedding_dimension()
        logger.info("本地 embedding 模型就绪，维度: %d", self._dim)

    def encode(self, text: str) -> list[float]:
        """对文本进行向量编码（同步，CPU 密集，调用方负责放到线程中）"""
        self._load()
        embedding = self._model.encode(text, normalize_embeddings=True)
        return embedding.tolist()


def get_local_provider() -> Optional[LocalEmbeddingProvider]:
    """获取本地 embedding 提供者（双重检查锁，懒加载）"""
    global _local_provider
    if _local_provider is not None:
        return _local_provider

    with _local_lock:
        if _local_provider is not None:
            return _local_provider
        try:
            _local_provider = LocalEmbeddingProvider()
            return _local_provider
        except ImportError:
            logger.debug("sentence-transformers 未安装，本地 embedding 不可用")
            return None
        except Exception as e:
            logger.warning("本地 embedding 模型加载失败: %s", e)
            return None


def has_local_embedding() -> bool:
    """检查本地 embedding 是否可用（不触发模型加载）"""
    global _local_provider
    if _local_provider is not None:
        return True
    try:
        import sentence_transformers  # noqa: F401

        return True
    except ImportError:
        return False
