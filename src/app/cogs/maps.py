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

from app.constants import LEVEL_NAMES, SDK_LEVEL_ID_ALIASES, DISCORD_EMPTY_STRING

log = logging.getLogger(__name__)


COLUMNS = 3
NAME_WIDTH = max(len(name) for name in LEVEL_NAMES.values())

def build_maps_message() -> str:
    sdk_ids = {api_id: sdk_id for sdk_id, api_id in SDK_LEVEL_ID_ALIASES.items()}
    entries = [f"{DISCORD_EMPTY_STRING}", ":round_pushpin: Portal Map Names"]
    entries.extend([
        f"- **{name}** - `{sdk_ids.get(level, level)}`"
        for level, name in sorted(LEVEL_NAMES.items(), key=lambda item: item[1].lower())
    ])
    return "\n".join(entries)


class MapsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="maps", description="List Portal map names and their level ids"
    )
    @app_commands.rename(post_in_channel="post-in-channel")
    @app_commands.describe(
        post_in_channel="Should the map list be posted in the channel?"
    )
    async def maps(
        self, interaction: discord.Interaction, post_in_channel: bool = False
    ) -> None:
        await interaction.response.send_message(
            build_maps_message(), ephemeral=not post_in_channel
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MapsCog(bot))


if __name__ == "__main__":
    print(build_maps_message())
