"""Look up Portal experience details from the gametools API.

Given an experience code entered when scheduling a playtest, fetch the shared
playground metadata so the announcement can show it. The upstream JSON is deeply
nested and inconsistent, so parsing is defensive throughout and any failure
degrades to "no details".
"""

from __future__ import annotations

import logging

import aiohttp

from ... import maps_data

log = logging.getLogger(__name__)

API_URL = "https://api.gametools.network/bf6/shared_playground/"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)


class Experience:
    """A parsed slice of the gametools experience payload."""

    def __init__(
        self,
        name: str,
        description: str,
        maps: list[str],
        tags: list[str],
        likes: int,
        image: str | None,
        players: str | None,
        updated: int | None,
    ) -> None:
        self.name = name
        self.description = description
        self.maps = maps
        self.tags = tags
        self.likes = likes
        self.image = image
        # Human-readable player count, e.g. "64 (32v32)", or None if unknown.
        self.players = players
        # Last-updated time as epoch seconds, or None if unknown.
        self.updated = updated


def _first(seq: list | None) -> dict | None:
    """Return the first element of a list if it's a non-empty list, else None."""
    if isinstance(seq, list) and seq:
        first = seq[0]
        return first if isinstance(first, dict) else None
    return None


def _friendly_map_name(entry: dict) -> str | None:
    """Resolve a map's display name.

    The curated map list is the source of truth; fall back to the API's
    ``mapname`` (or the raw level id) only for ids we don't have.
    """
    level = (entry.get("levelName") or "").strip()
    mapname = (entry.get("mapname") or "").strip()
    return maps_data.level_name(level) or mapname or level or None


def _player_count(entry: dict) -> str | None:
    """Format a map's team capacities as "total (AvB)", e.g. "64 (32v32)"."""
    teams = ((entry.get("teamComposition") or {}).get("teams")) or []
    caps = [
        int(t["capacity"]) for t in teams if isinstance(t, dict) and t.get("capacity")
    ]
    if not caps:
        return None
    total = sum(caps)
    return f"{total} ({'v'.join(str(c) for c in caps)})"


def parse_experience(payload: dict) -> Experience | None:
    """Extract the useful fields from the gametools response.

    Returns ``None`` when the code is unknown (the API returns an empty
    ``result`` list) or the payload isn't shaped as expected.
    """
    outer = _first(payload.get("result"))
    design = _first(outer.get("result")) if outer else None
    if design is None:
        return None

    name = str(design.get("name") or "Unknown Experience")
    description = str(design.get("configDescription") or "")
    likes = int(design.get("likes") or 0)

    play_design = design.get("playElementDesign") or {}
    rotation = play_design.get("mapRotation") or {}

    maps: list[str] = []
    image: str | None = None
    players: str | None = None
    for entry in rotation.get("maps") or []:
        if not isinstance(entry, dict):
            continue
        map_name = _friendly_map_name(entry)
        if map_name:
            maps.append(map_name)
        if image is None and entry.get("image"):
            image = str(entry["image"])
        # Player count is consistent across a rotation; take the first we find.
        if players is None:
            players = _player_count(entry)

    updated_raw = (play_design.get("updated") or {}).get("seconds")
    updated = int(updated_raw) if updated_raw else None

    tags: list[str] = []
    for tag in play_design.get("tags") or []:
        translations = ((tag or {}).get("translation") or {}).get("translations") or []
        # kind "6" is the human-readable tag title (e.g. "Custom Logic").
        title = next(
            (t.get("localizedText") for t in translations if t.get("kind") == "6"),
            None,
        )
        if title:
            tags.append(str(title))

    return Experience(name, description, maps, tags, likes, image, players, updated)


async def fetch_experience(code: str) -> Experience | None:
    """Fetch and parse experience details for ``code``.

    Returns ``None`` when the code is invalid or the lookup fails for any
    reason; callers treat that as "nothing to show".
    """
    params = {"experiencecode": code.strip().upper(), "lang": "en-us"}
    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            async with session.get(API_URL, params=params) as response:
                response.raise_for_status()
                payload = await response.json()
    except aiohttp.ClientError, TimeoutError:
        log.warning("Failed to fetch experience for code %r", code, exc_info=True)
        return None

    try:
        return parse_experience(payload)
    except Exception:
        log.warning("Failed to parse experience for code %r", code, exc_info=True)
        return None
