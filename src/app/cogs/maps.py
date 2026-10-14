"""Map reference lookup and the moderator commands that maintain it.

Surfaces the curated level id -> display name mapping from the ``maps`` table via
``/maps``, so people can find the id a map goes by in Portal without digging
through the code.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands

from app import db, maps_data, permissions
from app.config import env
from app.constants import DISCORD_EMPTY_STRING

log = logging.getLogger(__name__)


def build_maps_message(season: int | None = None) -> str:
    heading = ":round_pushpin: Portal Map Names"
    if season is not None:
        heading = f"{heading} — Season {season}"
    entries = [DISCORD_EMPTY_STRING, heading]
    entries.extend(
        f"- **{entry.name}** - `{entry.sdk_id or entry.level_id}`"
        for entry in maps_data.entries(season)
    )
    entries.append(
        "-# Also see : https://discord.com/channels/870246147455877181/1426307982580256821"
    )
    return "\n".join(entries)


def _level_id_problem(level_id: str) -> str | None:
    if not level_id.strip() or any(char.isspace() for char in level_id):
        return "A level id cannot be empty or contain whitespace."
    return None


def _season_problem(season: int | None) -> str | None:
    if season is not None and season < 1:
        return "A season must be a positive number."
    return None


async def _refuse_non_moderator(interaction: discord.Interaction) -> bool:
    if permissions.is_moderator(interaction.user):
        return False
    await interaction.response.send_message(
        "You need a moderator role to edit the map list.", ephemeral=True
    )
    return True


async def _report_unknown_map(interaction: discord.Interaction, level_id: str) -> None:
    await interaction.response.send_message(
        f"`{level_id}` is not in the map list.", ephemeral=True
    )


async def _write(
    interaction: discord.Interaction,
    write: Callable[[], Awaitable[None]],
    confirmation: str,
) -> None:
    try:
        await write()
        await maps_data.load()
    except Exception:
        log.exception("Failed to update the map list")
        return await interaction.response.send_message(
            "Couldn't update the map list. Please contact an admin.", ephemeral=True
        )
    await interaction.response.send_message(confirmation, ephemeral=True)


class MapsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="maps", description="List Portal map names and their level ids"
    )
    @app_commands.rename(post_in_channel="post-in-channel")
    @app_commands.describe(
        post_in_channel="Should the map list be posted in the channel?",
        season="Only list maps added in this season",
    )
    async def maps(
        self,
        interaction: discord.Interaction,
        post_in_channel: bool = False,
        season: int | None = None,
    ) -> None:
        problem = _season_problem(season)
        if problem is not None:
            return await interaction.response.send_message(problem, ephemeral=True)
        await interaction.response.send_message(
            build_maps_message(season), ephemeral=not post_in_channel
        )

    map_group = app_commands.Group(
        name="map", description="Manage the curated map list"
    )

    async def _autocomplete_level_id(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        needle = current.lower()
        matches = [
            entry
            for entry in maps_data.entries()
            if needle in entry.level_id.lower() or needle in entry.name.lower()
        ]
        return [
            app_commands.Choice(
                name=f"{entry.name} ({entry.level_id})", value=entry.level_id
            )
            for entry in matches[:25]
        ]

    @map_group.command(name="add", description="Add a map to the curated list")
    @app_commands.describe(
        level_id="Level id Portal reports, e.g. MP_Badlands",
        name="Name to show in the map list",
        sdk_id="SDK spelling of the level id, when it differs from the Portal one",
        season="Season the map was added in",
    )
    async def map_add(
        self,
        interaction: discord.Interaction,
        level_id: str,
        name: str,
        sdk_id: str | None = None,
        season: int | None = None,
    ) -> None:
        if await _refuse_non_moderator(interaction):
            return
        problem = _level_id_problem(level_id) or _season_problem(season)
        if problem is not None:
            return await interaction.response.send_message(problem, ephemeral=True)
        if maps_data.get(level_id) is not None:
            return await interaction.response.send_message(
                f"`{level_id}` is already listed. Use `/map rename` to change its name.",
                ephemeral=True,
            )
        owner = None if sdk_id is None else maps_data.sdk_id_owner(sdk_id)
        if owner is not None:
            return await interaction.response.send_message(
                f"SDK id `{sdk_id}` is already used by `{owner.level_id}`.",
                ephemeral=True,
            )
        await _write(
            interaction,
            lambda: db.upsert_map(level_id, name, sdk_id, season),
            f"Added **{name}** (`{level_id}`).",
        )

    @map_group.command(name="remove", description="Remove a map from the curated list")
    @app_commands.autocomplete(level_id=_autocomplete_level_id)
    async def map_remove(self, interaction: discord.Interaction, level_id: str) -> None:
        if await _refuse_non_moderator(interaction):
            return
        entry = maps_data.get(level_id)
        if entry is None:
            return await _report_unknown_map(interaction, level_id)
        await _write(
            interaction,
            lambda: db.delete_map(level_id),
            f"Removed **{entry.name}** (`{level_id}`).",
        )

    @map_group.command(name="rename", description="Change a map's display name")
    @app_commands.describe(level_id="Map to rename", name="New display name")
    @app_commands.autocomplete(level_id=_autocomplete_level_id)
    async def map_rename(
        self, interaction: discord.Interaction, level_id: str, name: str
    ) -> None:
        if await _refuse_non_moderator(interaction):
            return
        entry = maps_data.get(level_id)
        if entry is None:
            return await _report_unknown_map(interaction, level_id)
        if not name.strip():
            return await interaction.response.send_message(
                "A map name cannot be empty.", ephemeral=True
            )
        await _write(
            interaction,
            lambda: db.upsert_map(level_id, name, entry.sdk_id, entry.season),
            f"Renamed `{level_id}` to **{name}**.",
        )

    @map_group.command(
        name="set-sdk-id", description="Set or clear the SDK spelling of a level id"
    )
    @app_commands.describe(
        level_id="Map to update",
        sdk_id="SDK spelling of the level id; omit to clear it",
    )
    @app_commands.autocomplete(level_id=_autocomplete_level_id)
    async def map_set_sdk_id(
        self,
        interaction: discord.Interaction,
        level_id: str,
        sdk_id: str | None = None,
    ) -> None:
        if await _refuse_non_moderator(interaction):
            return
        entry = maps_data.get(level_id)
        if entry is None:
            return await _report_unknown_map(interaction, level_id)
        if sdk_id is not None:
            problem = _level_id_problem(sdk_id)
            if problem is not None:
                return await interaction.response.send_message(problem, ephemeral=True)
            owner = maps_data.sdk_id_owner(sdk_id)
            if owner is not None and owner.level_id != level_id:
                return await interaction.response.send_message(
                    f"SDK id `{sdk_id}` is already used by `{owner.level_id}`.",
                    ephemeral=True,
                )
        confirmation = (
            f"Cleared the SDK id for `{level_id}`."
            if sdk_id is None
            else f"SDK id for `{level_id}` is now `{sdk_id}`."
        )
        await _write(
            interaction,
            lambda: db.upsert_map(level_id, entry.name, sdk_id, entry.season),
            confirmation,
        )

    @map_group.command(name="set-season", description="Set or clear a map's season")
    @app_commands.describe(
        level_id="Map to update",
        season="Season the map was added in; omit to clear it",
    )
    @app_commands.autocomplete(level_id=_autocomplete_level_id)
    async def map_set_season(
        self,
        interaction: discord.Interaction,
        level_id: str,
        season: int | None = None,
    ) -> None:
        if await _refuse_non_moderator(interaction):
            return
        entry = maps_data.get(level_id)
        if entry is None:
            return await _report_unknown_map(interaction, level_id)
        problem = _season_problem(season)
        if problem is not None:
            return await interaction.response.send_message(problem, ephemeral=True)
        confirmation = (
            f"Cleared the season for `{level_id}`."
            if season is None
            else f"`{level_id}` is now in season {season}."
        )
        await _write(
            interaction,
            lambda: db.upsert_map(level_id, entry.name, entry.sdk_id, season),
            confirmation,
        )


async def _print_maps() -> None:
    await db.init_db(env.BOT_SETTINGS.DB_PATH)
    await maps_data.load()
    print(build_maps_message())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MapsCog(bot))


if __name__ == "__main__":
    asyncio.run(_print_maps())
