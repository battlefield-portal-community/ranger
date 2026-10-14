"""Shared authorization checks for cog commands."""

from __future__ import annotations

import discord

from .config import env


def is_moderator(user: discord.User | discord.Member) -> bool:
    """True if the user holds one of the configured moderator/admin roles."""
    mod_role_ids = set(env.PLAYTEST_COG_SETTINGS.MOD_ROLE_IDS)
    roles = getattr(user, "roles", [])
    return any(role.id in mod_role_ids for role in roles)
