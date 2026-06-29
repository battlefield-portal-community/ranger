"""Async SQLite storage for the bot.

Holds two things:
- ``user_regions``: each user's last region selection, so the playtest modal can
  pre-fill it next time.
- ``bot_state``: small key/value state, currently the posted menu message id so we
  edit it on restart instead of posting a duplicate.

The database path is taken from :data:`app.config.env` and a module-level path is
cached by :func:`init_db`, so the accessor helpers can be called without passing
it around.
"""

from __future__ import annotations

import json

import aiosqlite

_db_path: str | None = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_regions (
    user_id INTEGER PRIMARY KEY,
    regions TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bot_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


async def init_db(path: str) -> None:
    """Create tables if needed and remember the database path."""
    global _db_path
    _db_path = path
    async with aiosqlite.connect(path) as conn:
        await conn.executescript(_SCHEMA)
        await conn.commit()


def _path() -> str:
    if _db_path is None:
        raise RuntimeError("init_db() must be called before using the database")
    return _db_path


async def get_user_regions(user_id: int) -> list[str]:
    """Return the user's saved region keys, or an empty list if none."""
    async with aiosqlite.connect(_path()) as conn:
        async with conn.execute(
            "SELECT regions FROM user_regions WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    if row is None:
        return []
    return json.loads(row[0])


async def set_user_regions(user_id: int, regions: list[str]) -> None:
    """Persist the user's region selection (upsert)."""
    async with aiosqlite.connect(_path()) as conn:
        await conn.execute(
            """
            INSERT INTO user_regions (user_id, regions) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET regions = excluded.regions
            """,
            (user_id, json.dumps(regions)),
        )
        await conn.commit()


async def get_state(key: str) -> str | None:
    """Return a stored state value, or None if the key is unset."""
    async with aiosqlite.connect(_path()) as conn:
        async with conn.execute(
            "SELECT value FROM bot_state WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row else None


async def set_state(key: str, value: str) -> None:
    """Store a state value (upsert)."""
    async with aiosqlite.connect(_path()) as conn:
        await conn.execute(
            """
            INSERT INTO bot_state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        await conn.commit()
