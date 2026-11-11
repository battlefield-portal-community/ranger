"""Async SQLite storage for the bot.

Holds:
- ``user_regions``: each user's last region selection, so the playtest modal can
  pre-fill it next time.
- ``playtests``: the details of each scheduled playtest, keyed to its announcement
  message so it can be looked up and edited later.
- ``bot_state``: small key/value state, currently the posted menu message id so we
  edit it on restart instead of posting a duplicate.
- ``maps``: the curated level id -> display name list, maintained from Discord.
- ``feedback_posts`` / ``feedback_events`` / ``feedback_fts``: the forum intake
  audit trail, the tag mirror and the dedupe index (see :mod:`app.cogs.feedback`).

The database path is taken from :data:`app.config.env` and a module-level path is
cached by :func:`init_db`, so the accessor helpers can be called without passing
it around.
"""

from __future__ import annotations

import json
import time
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
    code TEXT NOT NULL,
    scheduled_at INTEGER,
    ends_at INTEGER,
    event_id TEXT,
    end_warned INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS bot_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS maps (
    level_id TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    -- The Portal SDK spelling, when it differs from the API one, so a map still
    -- resolves whichever spelling arrives. NULL for most maps.
    sdk_id   TEXT UNIQUE,
    -- The season a map was added in, when it is known.
    season   INTEGER
);
CREATE TABLE IF NOT EXISTS feedback_posts (
    thread_id      INTEGER PRIMARY KEY,
    forum_id       INTEGER NOT NULL,
    -- 'bug' | 'feature'
    kind           TEXT    NOT NULL,
    reporter_id    TEXT    NOT NULL,
    summary        TEXT    NOT NULL,
    body           TEXT    NOT NULL,
    -- Mirror of the thread's own tags for later reporting, not an active state
    -- machine: 'open' means the thread carries no status tag.
    status         TEXT    NOT NULL DEFAULT 'open',
    status_at      INTEGER NOT NULL,
    created_at     INTEGER NOT NULL,
    -- A replayed or retried modal submit must not file a second thread.
    interaction_id TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_feedback_status
    ON feedback_posts (status, created_at);
CREATE TABLE IF NOT EXISTS feedback_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL,
    -- create | status | dedupe | error
    kind      TEXT    NOT NULL,
    actor_id  TEXT    NOT NULL,
    detail    TEXT,
    at        INTEGER NOT NULL
);
-- Needs FTS5 compiled into the SQLite build the bot runs on.
CREATE VIRTUAL TABLE IF NOT EXISTS feedback_fts
    USING fts5 (thread_id UNINDEXED, summary, body);
"""

# ``CREATE TABLE IF NOT EXISTS`` leaves older databases untouched, so columns added
# after the first release have to be backfilled with ALTER TABLE.
_PLAYTEST_MIGRATIONS = [
    ("scheduled_at", "INTEGER"),
    ("ends_at", "INTEGER"),
    ("event_id", "TEXT"),
    ("end_warned", "INTEGER NOT NULL DEFAULT 0"),
]


async def init_db(path: str) -> None:
    """Create tables if needed, apply pending migrations and remember the path."""
    global _db_path
    _db_path = path
    async with aiosqlite.connect(path) as conn:
        await conn.executescript(_SCHEMA)
        async with conn.execute("PRAGMA table_info(playtests)") as cur:
            existing = {row[1] for row in await cur.fetchall()}
        for name, decl in _PLAYTEST_MIGRATIONS:
            if name not in existing:
                await conn.execute(f"ALTER TABLE playtests ADD COLUMN {name} {decl}")
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
class MapEntry:
    """A curated map as stored in the ``maps`` table."""

    level_id: str
    name: str
    sdk_id: str | None
    season: int | None


@dataclass(frozen=True)
class Playtest:
    """A scheduled playtest as stored in the ``playtests`` table."""

    id: int
    user_id: str
    message_id: str
    regions: list[str]
    description: str
    code: str
    scheduled_at: int | None
    ends_at: int | None
    event_id: str | None
    end_warned: bool


_PLAYTEST_COLUMNS = """
    id, user_id, message_id, regions, description, code,
    scheduled_at, ends_at, event_id, end_warned
"""


def _row_to_playtest(row: tuple) -> Playtest:
    id_, user_id, msg_id, regions, description, code = row[:6]
    scheduled_at, ends_at, event_id, end_warned = row[6:]
    return Playtest(
        id_,
        user_id,
        msg_id,
        json.loads(regions),
        description,
        code,
        scheduled_at,
        ends_at,
        event_id,
        bool(end_warned),
    )


async def set_playtest(
    user_id: int,
    message_id: int,
    regions: list[str],
    description: str,
    code: str,
    scheduled_at: int | None = None,
) -> None:
    """Insert a playtest, or update it in place if one already exists for the
    announcement message (upsert, keyed on ``message_id``).

    The event columns are owned by the event lifecycle and deliberately left alone
    here, so an ordinary description edit cannot clobber a live event.
    """
    async with aiosqlite.connect(_path()) as conn:
        await conn.execute(
            """
            INSERT INTO playtests
                (user_id, message_id, regions, description, code, scheduled_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                user_id = excluded.user_id,
                regions = excluded.regions,
                description = excluded.description,
                code = excluded.code,
                scheduled_at = excluded.scheduled_at
            """,
            (
                str(user_id),
                str(message_id),
                json.dumps(regions),
                description,
                code,
                scheduled_at,
            ),
        )
        await conn.commit()


async def get_playtest(message_id: int) -> Playtest | None:
    """Return the playtest for an announcement message, or None if absent."""
    async with aiosqlite.connect(_path()) as conn:
        async with conn.execute(
            f"SELECT {_PLAYTEST_COLUMNS} FROM playtests WHERE message_id = ?",
            (str(message_id),),
        ) as cur:
            row = await cur.fetchone()
    return None if row is None else _row_to_playtest(row)


async def get_playtests_with_events() -> list[Playtest]:
    """Return every playtest that currently has a scheduled event attached."""
    async with aiosqlite.connect(_path()) as conn:
        async with conn.execute(
            f"SELECT {_PLAYTEST_COLUMNS} FROM playtests WHERE event_id IS NOT NULL"
        ) as cur:
            rows = await cur.fetchall()
    return [_row_to_playtest(row) for row in rows]


async def update_playtest_event(
    message_id: int,
    *,
    event_id: str | None,
    ends_at: int | None,
    end_warned: bool = False,
) -> None:
    """Set the event columns for a playtest (create, clear, reschedule or extend)."""
    async with aiosqlite.connect(_path()) as conn:
        await conn.execute(
            """
            UPDATE playtests SET event_id = ?, ends_at = ?, end_warned = ?
            WHERE message_id = ?
            """,
            (event_id, ends_at, int(end_warned), str(message_id)),
        )
        await conn.commit()


async def mark_end_warned(message_id: int) -> None:
    """Record that the creator has been pinged about the event's end time."""
    async with aiosqlite.connect(_path()) as conn:
        await conn.execute(
            "UPDATE playtests SET end_warned = 1 WHERE message_id = ?",
            (str(message_id),),
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


_MAP_COLUMNS = "level_id, name, sdk_id, season"


def _row_to_map(row: tuple) -> MapEntry:
    return MapEntry(*row)


async def list_maps() -> list[MapEntry]:
    """Return every curated map."""
    async with aiosqlite.connect(_path()) as conn:
        async with conn.execute(f"SELECT {_MAP_COLUMNS} FROM maps") as cur:
            rows = await cur.fetchall()
    return [_row_to_map(row) for row in rows]


async def upsert_map(
    level_id: str,
    name: str,
    sdk_id: str | None = None,
    season: int | None = None,
) -> None:
    """Insert a map, or overwrite the stored row with the same level id."""
    async with aiosqlite.connect(_path()) as conn:
        await conn.execute(
            """
            INSERT INTO maps (level_id, name, sdk_id, season) VALUES (?, ?, ?, ?)
            ON CONFLICT(level_id) DO UPDATE SET
                name = excluded.name,
                sdk_id = excluded.sdk_id,
                season = excluded.season
            """,
            (level_id, name, sdk_id, season),
        )
        await conn.commit()


async def delete_map(level_id: str) -> bool:
    """Remove a map, reporting whether a row was deleted."""
    async with aiosqlite.connect(_path()) as conn:
        cur = await conn.execute("DELETE FROM maps WHERE level_id = ?", (level_id,))
        deleted = cur.rowcount > 0
        await conn.commit()
    return deleted


async def seed_maps(entries: list[MapEntry]) -> None:
    """Insert maps that aren't stored yet, leaving existing rows untouched."""
    async with aiosqlite.connect(_path()) as conn:
        await conn.executemany(
            """
            INSERT OR IGNORE INTO maps (level_id, name, sdk_id, season)
            VALUES (?, ?, ?, ?)
            """,
            [(e.level_id, e.name, e.sdk_id, e.season) for e in entries],
        )
        await conn.commit()


@dataclass(frozen=True)
class FeedbackPost:
    """A filed forum post as stored in the ``feedback_posts`` table."""

    thread_id: int
    forum_id: int
    kind: str
    reporter_id: str
    summary: str
    body: str
    status: str
    status_at: int
    created_at: int
    interaction_id: str | None


_FEEDBACK_COLUMN_NAMES = (
    "thread_id",
    "forum_id",
    "kind",
    "reporter_id",
    "summary",
    "body",
    "status",
    "status_at",
    "created_at",
    "interaction_id",
)
_FEEDBACK_COLUMNS = ", ".join(_FEEDBACK_COLUMN_NAMES)
_FEEDBACK_JOIN_COLUMNS = ", ".join(f"p.{name}" for name in _FEEDBACK_COLUMN_NAMES)


def _row_to_feedback(row: tuple) -> FeedbackPost:
    return FeedbackPost(
        thread_id=row[0],
        forum_id=row[1],
        kind=row[2],
        reporter_id=str(row[3]),
        summary=row[4],
        body=row[5],
        status=row[6],
        status_at=row[7],
        created_at=row[8],
        interaction_id=row[9],
    )


async def create_feedback(
    *,
    thread_id: int,
    forum_id: int,
    kind: str,
    reporter_id: int | str,
    summary: str,
    body: str,
    interaction_id: str | None = None,
    status: str = "open",
    created_at: int | None = None,
) -> bool:
    """Record a filed post, reporting whether a row was inserted.

    Returns ``False`` when this thread is already recorded or this interaction
    was already used to file one, so a replayed submit creates nothing.
    """
    now = int(time.time())
    async with aiosqlite.connect(_path()) as conn:
        cur = await conn.execute(
            """
            INSERT OR IGNORE INTO feedback_posts
                (thread_id, forum_id, kind, reporter_id, summary, body,
                 status, status_at, created_at, interaction_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thread_id,
                forum_id,
                kind,
                str(reporter_id),
                summary,
                body,
                status,
                now,
                now if created_at is None else int(created_at),
                interaction_id,
            ),
        )
        inserted = cur.rowcount > 0
        await conn.commit()
    return inserted


async def get_feedback(thread_id: int) -> FeedbackPost | None:
    """Return the filed post for a thread, or None if it was not filed by us."""
    async with aiosqlite.connect(_path()) as conn:
        async with conn.execute(
            f"SELECT {_FEEDBACK_COLUMNS} FROM feedback_posts WHERE thread_id = ?",
            (thread_id,),
        ) as cur:
            row = await cur.fetchone()
    return None if row is None else _row_to_feedback(row)


async def set_feedback_status(
    thread_id: int, status: str, *, status_at: int | None = None
) -> bool:
    """Mirror a thread's status tag, reporting whether a row was updated."""
    async with aiosqlite.connect(_path()) as conn:
        cur = await conn.execute(
            "UPDATE feedback_posts SET status = ?, status_at = ? WHERE thread_id = ?",
            (
                status,
                int(time.time()) if status_at is None else int(status_at),
                thread_id,
            ),
        )
        updated = cur.rowcount > 0
        await conn.commit()
    return updated


async def list_feedback(
    status: str | None = None,
    forum_id: int | None = None,
    limit: int | None = None,
) -> list[FeedbackPost]:
    """Return filed posts, newest first, optionally filtered."""
    query = f"SELECT {_FEEDBACK_COLUMNS} FROM feedback_posts"
    conditions: list[str] = []
    params: list[object] = []
    if status is not None:
        conditions.append("status = ?")
        params.append(status)
    if forum_id is not None:
        conditions.append("forum_id = ?")
        params.append(forum_id)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at DESC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    async with aiosqlite.connect(_path()) as conn:
        async with conn.execute(query, params) as cur:
            rows = await cur.fetchall()
    return [_row_to_feedback(row) for row in rows]


async def count_by_status() -> dict[str, int]:
    """Return how many filed posts sit in each status."""
    async with aiosqlite.connect(_path()) as conn:
        async with conn.execute(
            "SELECT status, COUNT(*) FROM feedback_posts GROUP BY status"
        ) as cur:
            rows = await cur.fetchall()
    return {row[0]: row[1] for row in rows}


async def log_feedback_event(
    thread_id: int,
    kind: str,
    actor_id: int | str,
    detail: str | None = None,
    *,
    at: int | None = None,
) -> None:
    """Append to the feedback audit trail."""
    async with aiosqlite.connect(_path()) as conn:
        await conn.execute(
            """
            INSERT INTO feedback_events (thread_id, kind, actor_id, detail, at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                thread_id,
                kind,
                str(actor_id),
                detail,
                int(time.time()) if at is None else int(at),
            ),
        )
        await conn.commit()


async def index_feedback(thread_id: int, summary: str, body: str) -> None:
    """(Re)index one post for dedupe lookups."""
    async with aiosqlite.connect(_path()) as conn:
        await conn.execute("DELETE FROM feedback_fts WHERE thread_id = ?", (thread_id,))
        await conn.execute(
            "INSERT INTO feedback_fts (thread_id, summary, body) VALUES (?, ?, ?)",
            (thread_id, summary, body),
        )
        await conn.commit()


async def search_feedback(match: str, limit: int = 20) -> list[FeedbackPost]:
    """Search the dedupe index with an already-quoted FTS5 ``MATCH`` expression."""
    async with aiosqlite.connect(_path()) as conn:
        async with conn.execute(
            f"""
            SELECT {_FEEDBACK_JOIN_COLUMNS}
            FROM feedback_fts f JOIN feedback_posts p ON p.thread_id = f.thread_id
            WHERE feedback_fts MATCH ?
            ORDER BY bm25(feedback_fts)
            LIMIT ?
            """,
            (match, limit),
        ) as cur:
            rows = await cur.fetchall()
    return [_row_to_feedback(row) for row in rows]
