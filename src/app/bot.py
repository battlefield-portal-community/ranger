"""The Ranger Discord bot.

A thin :class:`discord.ext.commands.Bot` subclass that initialises the database,
auto-discovers cogs under ``app/cogs/`` and syncs application commands to the
configured guild. Feature behaviour (persistent views, menus, commands) lives in
the cogs themselves so this module stays generic.
"""

from __future__ import annotations

import logging
import json, math, time
from pathlib import Path

import discord
from discord.ext import commands, tasks

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

    def write_health_state(self) -> None:
        """Write the current health state for the Docker health probe"""

        """Normalizing latency value"""
        if math.isnan(self.latency):
            latency = None

        state = {
            "timestamp": time.time(),
            "latency": self.latency,
        }

        path = Path(env.BOT_SETTINGS.HEALTH_STATE_FILE)
        tmp_path = path.with_suffix(path.suffix + ".tmp")

        tmp_path.write_text(json.dumps(state))
        tmp_path.replace(path)  # To avoid the race condition

    @tasks.loop(seconds=env.BOT_SETTINGS.HEALTH_HEARTBEAT_INTERVAL)
    async def health_loop(self):
        try:
            self.write_health_state()
        except Exception:
            log.exception("Failed to update the health state")

    async def setup_hook(self) -> None:
        await init_db(env.BOT_SETTINGS.DB_PATH)
        await self._load_cogs()

        guild = discord.Object(id=env.BOT_SETTINGS.GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        log.info("Synced application commands to guild %s", env.BOT_SETTINGS.GUILD_ID)

        # self.health_loop.change_interval(seconds = env.BOT_SETTINGS.HEALTH_HEARTBEAT_INTERVAL)
        self.health_loop.start()

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
        await self.change_presence(status=discord.Status.online)
        log.info("Logged in as %s (id=%s)", user, user.id if user else "?")
