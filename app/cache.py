import sqlite3
from contextlib import closing
from pathlib import Path


class Cache:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def get(self, key: str) -> str | None:
        with closing(self._connect()) as db:
            row = db.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set(self, key: str, value: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("INSERT OR REPLACE INTO cache (key, value) VALUES (?, ?)", (key, value))
