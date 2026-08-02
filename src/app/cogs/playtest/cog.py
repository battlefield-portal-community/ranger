"""The playtest cog: slash commands and the persistent menu message."""

from __future__ import annotations

import logging
import time

import discord
from discord import app_commands, TextChannel, Message
from discord.ext import commands, tasks

from ... import db, permissions
from ...config import env
from . import events
from .announcements import get_announcement_channel
from .ui import PlaytestMenuView, UpdatePlaytestModal, build_playtest_modal

log = logging.getLogger(__name__)

MENU_STATE_KEY = "menu_message_id"


class PlaytestCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._menu_ensured = False

    async def cog_load(self) -> None:
        # Re-register the persistent view so the button keeps working after a restart.
        self.bot.add_view(PlaytestMenuView())
        self.event_scheduler.start()

    async def cog_unload(self) -> None:
        self.event_scheduler.cancel()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._menu_ensured:
            return
        self._menu_ensured = True
        try:
            await self.ensure_menu_message()
        except Exception:
            self._menu_ensured = False
            log.exception("Failed to ensure the playtest menu message")

    @app_commands.command(
        name="schedule-playtest", description="Schedule a new playtest session"
    )
    async def schedule_playtest(self, interaction: discord.Interaction) -> None:
        saved = await db.get_user_regions(interaction.user.id)
        await interaction.response.send_modal(build_playtest_modal(saved))

    @app_commands.command(
        name="update-playtest", description="Update the playtest menu message"
    )
    async def update_playtest(self, interaction: discord.Interaction) -> Message | None:
        try:
            channel = interaction.channel
            assert isinstance(channel, discord.Thread)
        except AssertionError:
            log.info("interaction was not sent in a thread")
            return await interaction.response.send_message(
                "This command can only be used in a thread", ephemeral=True
            )
        except discord.NotFound:
            log.info("thread message not found")
            return await interaction.response.send_message(
                "Thread message not found", ephemeral=True
            )

        playtest = await db.get_playtest(channel.id)
        if playtest is None:
            return await interaction.response.send_message(
                "This thread is not a playtest thread", ephemeral=True
            )

        # Only the original scheduler or a moderator may update the playtest.
        is_scheduler = str(interaction.user.id) == playtest.user_id
        if not (is_scheduler or permissions.is_moderator(interaction.user)):
            return await interaction.response.send_message(
                "Only the playtest's scheduler or a moderator can update it",
                ephemeral=True,
            )

        # A playtest thread shares its id with its announcement message.
        try:
            message = await channel.parent.fetch_message(channel.id)
        except discord.NotFound:
            msg = "Playtest message not found"
            log.warning(msg)
            return await interaction.response.send_message(msg, ephemeral=True)
        except discord.Forbidden:
            msg = "I don't have permission to fetch the playtest message"
            log.warning(msg)
            return await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            msg = "Failed to fetch the playtest message"
            log.exception(msg)
            return await interaction.response.send_message(msg, ephemeral=True)

        announcement_channel = await get_announcement_channel(interaction.guild)

        if announcement_channel is None:
            return await interaction.response.send_message(
                "Couldn't find the announcement channel. Please contact an admin.",
                ephemeral=True,
            )

        if channel.parent != announcement_channel:
            return await interaction.response.send_message(
                f"Thread was not created in {announcement_channel.mention} channel"
            )
        if self.bot.user != message.author:
            return await interaction.response.send_message(
                f"This thread was not started by {self.bot.user.mention}",
                ephemeral=True,
            )

        return await interaction.response.send_modal(
            UpdatePlaytestModal.from_playtest(playtest, message)
        )

    async def ensure_menu_message(self) -> None:
        """Post the menu message once, or edit the existing one on restart."""
        channel_id = env.PLAYTEST_COG_SETTINGS.MENU_CHANNEL_ID
        channel: TextChannel = self.bot.get_channel(
            channel_id
        ) or await self.bot.fetch_channel(channel_id)

        embed = discord.Embed(
            title="🎮 Playtest Scheduler",
            description=(
                "Click the button below to schedule a new playtest session.\n"
                "You'll add a description and choose the regions to ping.\n"
                "Then the bot will post an announcement and open a thread for the playtest."
            ),
            color=discord.Color.blurple(),
        )
        view = PlaytestMenuView()

        stored = await db.get_state(MENU_STATE_KEY)
        if stored:
            try:
                message = await channel.fetch_message(int(stored))
                await message.edit(embed=embed, view=view)
                log.info("Refreshed existing playtest menu message %s", stored)
                return
            except discord.NotFound:
                log.info("Stored menu message %s gone; posting a new one", stored)

        message = await channel.send(embed=embed, view=view)
        await db.set_state(MENU_STATE_KEY, str(message.id))
        log.info("Posted new playtest menu message %s", message.id)

    @staticmethod
    async def resolve_playtest_thread(
        guild: discord.Guild, message_id: str
    ) -> discord.Thread | None:
        """Resolve a playtest thread, which shares its id with its announcement."""
        thread = guild.get_thread(int(message_id))
        if thread is not None:
            return thread
        try:
            channel = await guild.fetch_channel(int(message_id))
        except discord.HTTPException:
            log.exception("Couldn't fetch playtest thread %s", message_id)
            return None
        return channel if isinstance(channel, discord.Thread) else None

    @tasks.loop(seconds=60)
    async def event_scheduler(self) -> None:
        """Start, warn about and end playtest events as their times come around."""
        now = int(time.time())
        rows = await db.get_playtests_with_events()
        if not rows:
            return

        guild = self.bot.get_guild(env.BOT_SETTINGS.GUILD_ID)
        if guild is None:
            return

        for row in rows:
            try:
                await self.advance_playtest_event(guild, row, now)
            # A status transition that Discord rejects raises ValueError, and any
            # single row's failure must not take down the rest of the tick.
            except ValueError:
                log.warning(
                    "Skipping playtest %s: event %s rejected the transition",
                    row.message_id,
                    row.event_id,
                )
            except Exception:
                log.exception("Failed to advance playtest event %s", row.message_id)

    @event_scheduler.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()

    async def advance_playtest_event(
        self, guild: discord.Guild, row: db.Playtest, now: int
    ) -> None:
        """Move one playtest's event through start, end warning and end."""
        message_id = int(row.message_id)
        event = await events.fetch_event(guild, row.event_id)

        # Gone, or a moderator already ended or cancelled it by hand.
        if event is None or event.status in (
            discord.EventStatus.completed,
            discord.EventStatus.cancelled,
        ):
            await db.update_playtest_event(message_id, event_id=None, ends_at=None)
            return

        if (
            event.status is discord.EventStatus.scheduled
            and row.scheduled_at is not None
            and row.scheduled_at <= now
        ):
            # The bot was down for the whole window, so there is nothing left to run.
            if row.ends_at is not None and row.ends_at <= now:
                await events.cancel_event(event)
                await db.update_playtest_event(message_id, event_id=None, ends_at=None)
            else:
                await event.start()
            return

        if event.status is not discord.EventStatus.active or row.ends_at is None:
            return

        if now >= row.ends_at:
            await event.end()
            await db.update_playtest_event(message_id, event_id=None, ends_at=None)
            thread = await self.resolve_playtest_thread(guild, row.message_id)
            if thread is not None:
                try:
                    await thread.send("✅ Playtest event ended.")
                except discord.HTTPException:
                    log.exception("Failed to post the end notice in %s", row.message_id)
            return

        warn_at = row.ends_at - env.PLAYTEST_COG_SETTINGS.EVENT_END_WARN_MINUTES * 60
        if row.end_warned or now < warn_at:
            return

        thread = await self.resolve_playtest_thread(guild, row.message_id)
        if thread is None:
            log.warning("No thread to warn for playtest %s", row.message_id)
            return

        await thread.send(
            f"<@{row.user_id}> ⏰ this playtest's event ends <t:{row.ends_at}:R>. "
            "Use /extend-playtest to keep it going."
        )
        # Flagged only once the ping lands, so a failed send retries next tick.
        await db.mark_end_warned(message_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PlaytestCog(bot))
