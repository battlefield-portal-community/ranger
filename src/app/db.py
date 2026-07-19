"""Async SQLite storage for the bot.

Holds:
- ``user_regions``: each user's last region selection, so the playtest modal can
  pre-fill it next time.
- ``playtests``: the details of each scheduled playtest, keyed to its announcement
  message so it can be looked up and edited later.
- ``bot_state``: small key/value state, currently the posted menu message id so we
  edit it on restart instead of posting a duplicate.

The database path is taken from :data:`app.config.env` and a module-level path is
cached by :func:`init_db`, so the accessor helpers can be called without passing
it around.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import aiosqlite

_db_path: str | None = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_regions (
    user_id INTEGER PRIMARY KEY,
    regions TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS playtests (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    message_id TEXT NOT NULL UNIQUE,
    regions TEXT NOT NULL,
    description TEXT NOT NULL,
    code TEXT NOT NULL
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


@dataclass(frozen=True)
class Playtest:
    """A scheduled playtest as stored in the ``playtests`` table."""

    id: int
    user_id: str
    message_id: str
    regions: list[str]
    description: str
    code: str


async def set_playtest(
    user_id: int,
    message_id: int,
    regions: list[str],
    description: str,
    code: str,
) -> None:
    """Insert a playtest, or update it in place if one already exists for the
    announcement message (upsert, keyed on ``message_id``)."""
    async with aiosqlite.connect(_path()) as conn:
        await conn.execute(
            """
            INSERT INTO playtests (user_id, message_id, regions, description, code)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                user_id = excluded.user_id,
                regions = excluded.regions,
                description = excluded.description,
                code = excluded.code
            """,
            (str(user_id), str(message_id), json.dumps(regions), description, code),
        )
        await conn.commit()


async def get_playtest(message_id: int) -> Playtest | None:
    """Return the playtest for an announcement message, or None if absent."""
    async with aiosqlite.connect(_path()) as conn:
        async with conn.execute(
            """
            SELECT id, user_id, message_id, regions, description, code
            FROM playtests WHERE message_id = ?
            """,
            (str(message_id),),
        ) as cur:
            row = await cur.fetchone()
    if row is None:
        return None
    id_, user_id, msg_id, regions, description, code = row
    return Playtest(id_, user_id, msg_id, json.loads(regions), description, code)


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
