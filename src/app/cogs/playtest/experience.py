"""Look up Portal experience details from the gametools API.

Given an experience code entered when scheduling a playtest, fetch the shared
playground metadata and render it as a Discord embed posted into the playtest
thread. The upstream JSON is deeply nested and inconsistent, so parsing is
defensive throughout and any failure degrades to "no embed".
"""

from __future__ import annotations

import logging

import aiohttp
import discord

log = logging.getLogger(__name__)

API_URL = "https://api.gametools.network/bf6/shared_playground/"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)

# Level id -> display name. Used as a fallback when the API returns the raw
# level id (e.g. "MP_Aftermath_Portal") instead of a friendly map name.
LEVEL_NAMES = {
    "MP_Abbasid": "Siege of Cairo",
    "MP_Aftermath": "Empire State",
    "MP_Badlands": "Blackwell Fields",
    "MP_Battery": "Iberian Offensive",
    "MP_Capstone": "Liberation Peak",
    "MP_Contaminated": "Contaminated",
    "MP_Dumbo": "Manhattan Bridge",
    "MP_Eastwood": "Eastwood",
    "MP_FireStorm": "Operation Firestorm",
    "MP_Limestone": "Saints Quarter",
    "MP_Outskirts": "New Sobek City",
    "MP_Tungsten": "Mirak Valley",
    "MP_Granite_ClubHouse_Portal": "Golf Course",
    "MP_Granite_TechCampus_Portal": "Defense Nexus",
    "MP_Granite_MainStreet_Portal": "Downtown",
    "MP_Granite_Marina_Portal": "Marina",
    "MP_Portal_Sand": "Portal Sandbox",
    "MP_Granite_MilitaryRnD_Portal": "Area 22B",
    "MP_Granite_MilitaryStorage_Portal": "Redline Storage",
    "MP_Granite_Underground_Portal": "Complex 3",
    "MP_Subsurface": "Hagental Base",
    "MP_GolmudRailway": "Railway to Golmud",
    "MP_Plaza": "Cairo Bazaar",
    "MP_Aftermath_Portal": "Bellum1988's Operation Metro",
}


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

    Our curated :data:`LEVEL_NAMES` is the source of truth; fall back to the
    API's ``mapname`` (or the raw level id) only for ids we don't have.
    """
    level = (entry.get("levelName") or "").strip()
    mapname = (entry.get("mapname") or "").strip()
    return LEVEL_NAMES.get(level) or mapname or level or None


def _player_count(entry: dict) -> str | None:
    """Format a map's team capacities as "total (AvB)", e.g. "64 (32v32)"."""
    teams = ((entry.get("teamComposition") or {}).get("teams")) or []
    caps = [int(t["capacity"]) for t in teams if isinstance(t, dict) and t.get("capacity")]
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
    except (aiohttp.ClientError, TimeoutError):
        log.warning("Failed to fetch experience for code %r", code, exc_info=True)
        return None

    try:
        return parse_experience(payload)
    except Exception:
        log.warning("Failed to parse experience for code %r", code, exc_info=True)
        return None


async def post_experience_embed(thread: discord.abc.Messageable, code: str) -> None:
    """Look up ``code`` and post its details (or a warning) into ``thread``.

    Intended to run as a fire-and-forget background task after the scheduling
    flow finishes, since the network call can be slow. Swallows all errors so a
    failure here never surfaces as an unhandled task exception.
    """
    try:
        experience = await fetch_experience(code)
        if experience is not None:
            await thread.send(embed=build_experience_embed(experience))
        else:
            log.info("No experience found for code %r", code)
            await thread.send(
                f"⚠️ Couldn't find an experience for code `{code.strip().upper()}`."
            )
    except Exception:
        log.exception("Failed to post experience embed for code %r", code)


# Show at most this many map names inline; the rest collapse into "+N more".
MAX_MAPS_SHOWN = 8


def _maps_value(maps: list[str]) -> str:
    """Comma-joined map list, capped with a "+N more" suffix for long rotations."""
    shown = maps[:MAX_MAPS_SHOWN]
    value = ", ".join(f"`{name}`" for name in shown)
    remaining = len(maps) - len(shown)
    if remaining > 0:
        value += f" … +{remaining} more"
    return value


def build_experience_embed(experience: Experience) -> discord.Embed:
    """Render an experience as a Discord embed for the playtest thread."""
    embed = discord.Embed(
        title=f"🎮 {experience.name}",
        description=experience.description or None,
        color=discord.Color.blurple(),
    )
    if experience.players:
        embed.add_field(name="Players", value=experience.players, inline=True)
    if experience.likes:
        embed.add_field(name="Likes", value=f"👍 {experience.likes}", inline=True)
    if experience.updated:
        embed.add_field(
            name="Updated", value=f"<t:{experience.updated}:R>", inline=True
        )
    if experience.maps:
        embed.add_field(
            name=f"Maps ({len(experience.maps)})",
            value=_maps_value(experience.maps),
            inline=False,
        )
    if experience.tags:
        embed.add_field(name="Tags", value=", ".join(experience.tags), inline=False)
    if experience.image:
        embed.set_image(url=experience.image)
    embed.set_footer(text="Experience details via gametools.network")
    return embed
