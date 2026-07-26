"""Map reference lookup.

Surfaces the curated level id -> display name mapping from
:mod:`app.constants` via ``/maps``, so people can find the id a map goes by in
Portal without digging through the code.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..constants import LEVEL_NAMES, SDK_LEVEL_ID_ALIASES, DISCORD_EMPTY_STRING

log = logging.getLogger(__name__)


COLUMNS = 3


def build_maps_embed() -> discord.Embed:
    """Render the map name -> level id listing as an embed.

    Maps are spread across :data:`COLUMNS` inline fields so Discord lays them
    out side by side. Chunking by column rather than one field per map keeps
    the field count fixed, well clear of the 25-field limit however long the
    map list grows.

    Ids are shown the way the Portal SDK spells them, since that is what people
    reading this need to paste into an experience.
    """
    sdk_ids = {api_id: sdk_id for sdk_id, api_id in SDK_LEVEL_ID_ALIASES.items()}

    entries = [
        f"**{name}**\n`{sdk_ids.get(level, level)}`"
        for level, name in sorted(LEVEL_NAMES.items(), key=lambda item: item[1].lower())
    ]

    embed = discord.Embed(title="🗺️ Portal Map Names", color=discord.Color.blurple())

    # Ceiling division so the last column is the short one, not an extra one.
    per_column = -(-len(entries) // COLUMNS)
    for start in range(0, len(entries), per_column):
        embed.add_field(
            name=DISCORD_EMPTY_STRING,
            value="\n".join(entries[start : start + per_column]),
        )

    embed.set_footer(text=f"{len(entries)} maps")
    return embed


class MapsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="maps", description="List Portal map names and their level ids"
    )
    async def maps(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=build_maps_embed(), ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MapsCog(bot))
