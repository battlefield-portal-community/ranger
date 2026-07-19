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
    description: str,
    code: str,
    roles: list[discord.Role],
) -> list[str]:
    lines = [
        "# 🎮 New Playtest",
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
    message = await build_announcement_message(user_id, description, code, roles)
    return await channel.send(
        content="\n".join(message),
        allowed_mentions=discord.AllowedMentions(roles=roles or False),
    )


async def update_announcement(
    user_id: int,
    message: discord.Message,
    roles: list[discord.Role],
    description: str,
    code: str,
) -> None:
    """Edit the announcement to include the new details."""

    lines = await build_announcement_message(user_id, description, code, roles)
    await message.edit(
        content="\n".join(lines),
        allowed_mentions=discord.AllowedMentions(roles=roles or False),
    )
