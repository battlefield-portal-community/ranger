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

from ..constants import LEVEL_NAMES

log = logging.getLogger(__name__)


def build_maps_embed() -> discord.Embed:
    """Render the map name -> level id table as an embed.

    The whole table goes in the embed description as one code block. At ~60
    characters a row it stays well under Discord's 4096-character description
    limit; if the map list ever grows several times over, this needs paging.
    """
    rows = sorted(LEVEL_NAMES.items(), key=lambda item: item[1].lower())
    width = max(len(name) for _, name in rows)
    table = "\n".join(f"{name:<{width}}  {level}" for level, name in rows)

    embed = discord.Embed(
        title="🗺️ Portal Map Names",
        description=f"```\n{table}\n```",
        color=discord.Color.blurple(),
    )
    embed.set_footer(text=f"{len(rows)} maps")
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
