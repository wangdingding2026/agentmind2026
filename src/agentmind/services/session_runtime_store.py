import sqlite3
from pathlib import Path

from agentmind.storage import db as storage_db


class SessionRuntimeStore:
    def __init__(self, db_path: Path | str | None = None):
        self._configured_db_path = Path(db_path) if db_path is not None else None

    @property
    def db_path(self) -> Path:
        if self._configured_db_path is not None:
            return self._configured_db_path
        return storage_db.DATA_DIR / "runtime_state.db"

    def _connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _ensure_schema(self):
        conn = self._connect()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS active_discussions (
                user_id TEXT PRIMARY KEY,
                stop INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def upsert_discussion(self, user_id: str, stop: bool):
        self._ensure_schema()
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO active_discussions (user_id, stop, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                stop=excluded.stop,
                updated_at=excluded.updated_at
            """,
            (user_id, int(stop), storage_db.now_iso()),
        )
        conn.commit()
        conn.close()

    def delete_discussion(self, user_id: str):
        self._ensure_schema()
        conn = self._connect()
        conn.execute("DELETE FROM active_discussions WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()

    def list_discussions(self) -> dict[str, dict]:
        self._ensure_schema()
        conn = self._connect()
        rows = conn.execute(
            "SELECT user_id, stop FROM active_discussions ORDER BY user_id"
        ).fetchall()
        conn.close()
        return {row["user_id"]: {"stop": bool(row["stop"])} for row in rows}
