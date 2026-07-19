"""Announcement helpers for the playtest cog.

Build, post and edit the plain-text announcement that pings the selected region
roles when a playtest is scheduled or later updated.
"""

from __future__ import annotations

import logging

import discord
from discord import TextChannel

from ...config import env

log = logging.getLogger(__name__)

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
