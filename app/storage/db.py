"""SQLite with explicit migrations and foreign keys.

One connection, guarded by a lock; async callers use `await db.run(fn)` / helpers which hop to a thread.
Media files live on disk; the database stores relative paths + checksums.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def load_migrations(folder: Path = MIGRATIONS_DIR) -> list[str]:
    """migrations/0001_name.sql, 0002_... in order. The number must match the position."""
    files = sorted(folder.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    for i, f in enumerate(files, start=1):
        if int(f.name[:4]) != i:
            raise RuntimeError(f"migration numbering gap at {f.name}")
    return [f.read_text(encoding="utf-8") for f in files]


MIGRATIONS: list[str] = load_migrations()


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA busy_timeout = 5000")
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL")
        self.migrate()

    # ---------------------------------------------------------------- schema
    @property
    def version(self) -> int:
        return int(self._conn.execute("PRAGMA user_version").fetchone()[0])

    def migrate(self, migrations: list[str] | None = None) -> int:
        migrations = MIGRATIONS if migrations is None else migrations
        with self._lock:
            cur = self.version
            if cur > len(migrations):
                raise RuntimeError(f"database is newer (v{cur}) than this code (v{len(migrations)})")
            for i, sql in enumerate(migrations[cur:], start=cur + 1):
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    for stmt in split_sql(sql):
                        self._conn.execute(stmt)
                    self._conn.execute(f"PRAGMA user_version = {i}")
                    self._conn.execute("COMMIT")
                except Exception:
                    self._conn.execute("ROLLBACK")
                    raise
            return self.version

    # ---------------------------------------------------------------- sync helpers
    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def one(self, sql: str, params: tuple | dict = ()) -> dict | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, params: tuple | dict = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def insert(self, table: str, values: dict[str, Any]) -> int:
        cols = ", ".join(values)
        qs = ", ".join("?" for _ in values)
        with self._lock:
            cur = self._conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", tuple(values.values()))
            return int(cur.lastrowid)

    def update(self, table: str, key: Any, values: dict[str, Any], key_col: str = "id") -> int:
        if not values:
            return 0
        sets = ", ".join(f"{c} = ?" for c in values)
        with self._lock:
            cur = self._conn.execute(f"UPDATE {table} SET {sets} WHERE {key_col} = ?", (*values.values(), key))
            return cur.rowcount

    def tx(self, fn: Callable[["Database"], Any]) -> Any:
        """Run fn inside one transaction (all or nothing)."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                out = fn(self)
                self._conn.execute("COMMIT")
                return out
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    async def run(self, fn: Callable[..., Any], *args: Any) -> Any:
        return await asyncio.to_thread(fn, *args)

    # ---------------------------------------------------------------- settings
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value_json FROM settings WHERE key = ?", (key,))
        return json.loads(row["value_json"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.execute("INSERT INTO settings (key, value_json, updated_at) VALUES (?, ?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
                     (key, json.dumps(value, ensure_ascii=False), time.time()))

    def integrity_ok(self) -> bool:
        row = self._conn.execute("PRAGMA integrity_check").fetchone()
        fk = self._conn.execute("PRAGMA foreign_key_check").fetchall()
        return bool(row) and row[0] == "ok" and not fk

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def split_sql(sql: str) -> list[str]:
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    return [st.strip() for st in "\n".join(lines).split(";") if st.strip()]


def dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def loads(s: str | None, default: Any = None) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except ValueError:
        return default
