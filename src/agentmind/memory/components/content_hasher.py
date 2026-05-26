"""内容哈希去重 — SHA256 精确去重 + SimHash 模糊去重"""

import hashlib
import re

# 稳定 hash 函数（Python 内置 hash() 跨进程不稳定，用 MD5 截取）
def _stable_hash(s: str) -> int:
    return int.from_bytes(hashlib.md5(s.encode("utf-8")).digest()[:8], "big")


class ContentHasher:

    @staticmethod
    def sha256(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def simhash(content: str, bits: int = 64) -> int:
        """SimHash 模糊去重。对中文做了简单分词处理。"""
        tokens = ContentHasher._tokenize(content)
        weights = [0] * bits

        for token in tokens:
            h = _stable_hash(token)
            for i in range(bits):
                if (h >> i) & 1:
                    weights[i] += 1
                else:
                    weights[i] -= 1

        fingerprint = 0
        for i in range(bits):
            if weights[i] > 0:
                fingerprint |= (1 << i)
        return fingerprint

    @staticmethod
    def hamming_distance(a: int, b: int, bits: int = 64) -> int:
        xor = a ^ b
        return xor.bit_count()

    @staticmethod
    def is_similar(a: int, b: int, threshold: int = 3, bits: int = 64) -> bool:
        """Hamming distance <= threshold 视为相似"""
        return ContentHasher.hamming_distance(a, b, bits) <= threshold

    @staticmethod
    def _tokenize(content: str) -> list[str]:
        # 简单分词：中文按字+二元组，英文按词
        words = re.findall(r'[一-鿿]+|[a-zA-Z]+|\d+', content.lower())
        tokens = []
        for w in words:
            if re.match(r'[一-鿿]', w):
                tokens.append(w)
                # 二元组
                for i in range(len(w) - 1):
                    tokens.append(w[i:i + 2])
            else:
                tokens.append(w)
        return tokens if tokens else [content[:100]]
