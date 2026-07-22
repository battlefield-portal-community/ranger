"""Announcement helpers for the playtest cog.

Build, post and edit the plain-text announcement that pings the selected region
roles when a playtest is scheduled or later updated.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

import discord
from discord import TextChannel

from ...config import env

log = logging.getLogger(__name__)

# Discord rejects any message whose content exceeds this many characters.
DISCORD_MESSAGE_LIMIT = 2000

# Experience codes are always short (6 chars for a BF Portal code). We enforce
# this on the modal input so the announcement's fixed overhead stays bounded.
EXPERIENCE_CODE_MAX_LENGTH = 6

# A Discord snowflake (user id) is a 64-bit int, so at most 19 digits; round up
# to 20 for a little headroom.
MAX_SNOWFLAKE_DIGITS = 20

# Emoji and title pools for the announcement header. One of each is picked
# independently but deterministically per playtest (seeded on the announcement
# message id) so the header stays stable across edits.
ANNOUNCEMENT_EMOJIS = (
    "🚀",
    "⚡",
    "🔥",
    "🎉",
    "🕹️",
    "👾",
    "🎯",
    "🛠️",
    "🎮",
    "🧪",
    "🎲",
    "🏁",
    "💥",
    "🎖️",
    "🚁",
)

ANNOUNCEMENT_TITLES = (
    "Playtest Incoming",
    "Fresh Playtest Drop",
    "New Playtest Live",
    "Playtest Time",
    "Jump Into a Playtest",
    "Playtest Needs You",
    "New Playtest - Dive In",
    "Help Us Test This",
    "New Playtest",
    "New Experiment Live",
    "Playtest Just Dropped",
    "New Playtest Ready",
    "New Playtest Deployed",
    "New Mission: Playtest",
    "Playtest Inbound",
)


def pick_announcement_header(seed: int) -> str:
    """Deterministically pick an emoji and title so it's stable across edits."""
    emoji = ANNOUNCEMENT_EMOJIS[seed % len(ANNOUNCEMENT_EMOJIS)]
    title = ANNOUNCEMENT_TITLES[(seed // len(ANNOUNCEMENT_EMOJIS)) % len(ANNOUNCEMENT_TITLES)]
    return f"{emoji} {title}"


# Longest possible "# <emoji> <title>" line. The pools are static, so this is
# computed once at import.
_MAX_HEADER_LINE = len("# ") + max(
    len(pick_announcement_header(seed))
    for seed in range(len(ANNOUNCEMENT_EMOJIS) * len(ANNOUNCEMENT_TITLES))
)


def announcement_overhead(role_ids: Iterable[int]) -> int:
    """Worst-case length of everything in the announcement except the description.

    Every line built by :func:`build_announcement_message` other than the
    free-text description is bounded, so summing their maxima (plus joining
    newlines) tells us how many characters are left for the description.
    """
    code_line = len("**Experience Code:** ``") + EXPERIENCE_CODE_MAX_LENGTH

    mentions = [f"<@&{role_id}>" for role_id in role_ids]
    regions_line = (
        len("**Regions:** ")
        + sum(len(m) for m in mentions)
        + max(len(mentions) - 1, 0)  # single spaces between mentions
    )

    footer_line = len("-# scheduled by **<@>**") + MAX_SNOWFLAKE_DIGITS

    # 7 lines at most (header, blank, description, blank, code, regions, footer)
    # joined by "\n".
    newlines = 6

    return _MAX_HEADER_LINE + code_line + regions_line + footer_line + newlines


def description_char_budget(role_ids: Iterable[int]) -> int:
    """How many description characters fit before the message exceeds the limit."""
    return DISCORD_MESSAGE_LIMIT - announcement_overhead(role_ids)


async def get_announcement_channel(guild: discord.Guild | None) -> TextChannel | None:
    if not guild:
        return None
    try:
        channel_id = env.PLAYTEST_COG_SETTINGS.ANNOUNCE_CHANNEL_ID
        channel = guild.get_channel(channel_id) or await guild.fetch_channel(channel_id)
        assert isinstance(channel, TextChannel)
        return channel
    except AssertionError:
        log.exception("Announcement channel is not a TextChannel")

    return None


async def build_announcement_message(
    user_id: int,
    seed: int,
    description: str,
    code: str,
    roles: list[discord.Role],
) -> list[str]:
    lines = [
        f"# {pick_announcement_header(seed)}",
        "",
        description,
        "",
    ]
    if code:
        lines.append(f"**Experience Code:** `{code}`")
    lines.append(f"**Regions:** {' '.join(r.mention for r in roles) or '—'}")
    lines.append(f"-# scheduled by **<@{user_id}>**")
    return lines


async def send_announcement(
    user_id: int,
    channel: discord.abc.Messageable,
    roles: list[discord.Role],
    description: str,
    code: str,
) -> discord.Message:
    """Post the announcement as a plain text message (no embed)."""
    mentions = discord.AllowedMentions(roles=roles or False)
    # Post first so the message exists (its id also becomes the id of the thread
    # created from it), then re-render the header seeded on that id for a stable,
    # per-playtest header. Editing does not re-ping the roles.
    lines = await build_announcement_message(user_id, user_id, description, code, roles)
    message = await channel.send(content="\n".join(lines), allowed_mentions=mentions)
    lines = await build_announcement_message(
        user_id, message.id, description, code, roles
    )
    await message.edit(content="\n".join(lines), allowed_mentions=mentions)
    return message


async def update_announcement(
    user_id: int,
    message: discord.Message,
    roles: list[discord.Role],
    description: str,
    code: str,
) -> None:
    """Edit the announcement to include the new details."""

    lines = await build_announcement_message(
        user_id, message.id, description, code, roles
    )
    await message.edit(
        content="\n".join(lines),
        allowed_mentions=discord.AllowedMentions(roles=roles or False),
    )
