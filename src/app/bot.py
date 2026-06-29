"""The Ranger Discord bot.

A thin :class:`discord.ext.commands.Bot` subclass that initialises the database,
auto-discovers cogs under ``app/cogs/`` and syncs application commands to the
configured guild. Feature behaviour (persistent views, menus, commands) lives in
the cogs themselves so this module stays generic.
"""

from __future__ import annotations

import logging
from pathlib import Path

import discord
from discord.ext import commands

from .config import env
from .db import init_db

log = logging.getLogger(__name__)

COGS_DIR = Path(__file__).parent / "cogs"


class Ranger(commands.Bot):
    def __init__(self, **options) -> None:
        intents = discord.Intents.default()
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            **options,
        )

    async def setup_hook(self) -> None:
        await init_db(env.BOT_SETTINGS.DB_PATH)
        await self._load_cogs()

        guild = discord.Object(id=env.BOT_SETTINGS.GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        log.info("Synced application commands to guild %s", env.BOT_SETTINGS.GUILD_ID)

    async def _load_cogs(self) -> None:
        for path in sorted(COGS_DIR.glob("*.py")):
            if path.stem == "__init__":
                continue
            ext = f"app.cogs.{path.stem}"
            try:
                await self.load_extension(ext)
                log.info("Loaded cog %s", ext)
            except Exception:
                log.exception("Failed to load cog %s", ext)

    async def on_ready(self) -> None:
        user = self.user
        log.info("Logged in as %s (id=%s)", user, user.id if user else "?")
