"""文本切分 — 将超过阈值的文本按句边界切分为多个 chunk"""

import re

# 句子分隔符
_SENTENCE_BOUNDARY = re.compile(r'[。！？.!?\n]+')


class Chunker:

    def __init__(self, max_chars: int = 500):
        self.max_chars = max_chars

    def chunk(self, content: str, max_chars: int | None = None) -> list[str]:
        """将 content 切分为列表，每段不超过 max_chars 字符。"""
        threshold = max_chars or self.max_chars

        if len(content) <= threshold:
            return [content]

        # 按句分割
        sentences = _SENTENCE_BOUNDARY.split(content)
        sentences = [s.strip() for s in sentences if s.strip()]

        chunks = []
        current = ""
        for s in sentences:
            if len(current) + len(s) <= threshold:
                current += s + "。"
            else:
                if current:
                    chunks.append(current.rstrip("。"))
                # 如果单句过长，强制按字符切分
                if len(s) > threshold:
                    for i in range(0, len(s), threshold):
                        chunks.append(s[i:i + threshold])
                    current = ""
                else:
                    current = s + "。"
        if current:
            chunks.append(current.rstrip("。"))

        return chunks if chunks else [content[:threshold]]
