"""In-memory mirror of the curated map list.

:mod:`app.cogs.playtest.experience` resolves map names synchronously while
rendering an announcement, so the ``maps`` table is mirrored into dicts here
instead of being queried per lookup.
"""

from __future__ import annotations

from . import db
from .constants import LEVEL_NAMES, SDK_LEVEL_ID_ALIASES

_by_level: dict[str, db.MapEntry] = {}
_sdk_alias: dict[str, str] = {}


def _seed() -> list[db.MapEntry]:
    sdk_by_api = {api_id: sdk_id for sdk_id, api_id in SDK_LEVEL_ID_ALIASES.items()}
    return [
        db.MapEntry(level_id, name, sdk_by_api.get(level_id), None)
        for level_id, name in LEVEL_NAMES.items()
    ]


async def load() -> None:
    """Refresh the cache from the database, seeding it from the constants once.

    A failure propagates to the caller and leaves the previous cache in place, so
    lookups keep resolving against the last known list.
    """
    global _by_level, _sdk_alias
    entries = await db.list_maps()
    if not entries:
        await db.seed_maps(_seed())
        entries = await db.list_maps()
    _by_level = {entry.level_id: entry for entry in entries}
    _sdk_alias = {entry.sdk_id: entry.level_id for entry in entries if entry.sdk_id}


def entries(season: int | None = None) -> list[db.MapEntry]:
    """Return maps sorted by display name, optionally only those in a season."""
    selected = (
        list(_by_level.values())
        if season is None
        else [entry for entry in _by_level.values() if entry.season == season]
    )
    return sorted(selected, key=lambda entry: entry.name.lower())


def level_name(level_id: str) -> str | None:
    """Resolve a map's display name, accepting either id spelling."""
    entry = _by_level.get(_sdk_alias.get(level_id, level_id))
    return None if entry is None else entry.name


def get(level_id: str) -> db.MapEntry | None:
    """Return the stored map for an API level id."""
    return _by_level.get(level_id)


def sdk_id_owner(sdk_id: str) -> db.MapEntry | None:
    """Return the map already using an SDK id, if any."""
    level_id = _sdk_alias.get(sdk_id)
    return None if level_id is None else _by_level.get(level_id)
