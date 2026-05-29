"""FTS5 jieba tokenizer availability helper."""

import logging
import sqlite3

logger = logging.getLogger("agentmind")

_JIEBA_AVAILABLE: bool | None = None


def is_jieba_fts_available() -> bool:
    """检查当前 SQLite 编译是否支持 jieba tokenizer。结果缓存。"""
    global _JIEBA_AVAILABLE
    if _JIEBA_AVAILABLE is not None:
        return _JIEBA_AVAILABLE

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE _jieba_test USING fts5(x, tokenize='jieba')
        """)
        conn.execute("DROP TABLE _jieba_test")
        _JIEBA_AVAILABLE = True
    except Exception:
        _JIEBA_AVAILABLE = False
    finally:
        conn.close()
    return _JIEBA_AVAILABLE


def create_fts5_table(conn, table_name: str = "memory_cards_fts", prefer_jieba: bool = True) -> bool:
    """创建 FTS5 表。返回 True 表示用了 jieba，False 表示降级默认。"""
    if prefer_jieba and is_jieba_fts_available():
        try:
            conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {table_name} USING fts5(
                    memory_id, content, summary, tags,
                    tokenize='jieba'
                )
            """)
            return True
        except Exception:
            pass

    try:
        conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {table_name} USING fts5(
                memory_id, content, summary, tags
            )
        """)
    except Exception:
        pass
    return False
