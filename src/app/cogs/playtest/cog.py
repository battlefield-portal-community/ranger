"""The playtest cog: slash commands and the persistent menu message."""

from __future__ import annotations

import logging

import discord
from discord import app_commands, TextChannel, Message
from discord.ext import commands

from ... import db
from ...config import env
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

    @staticmethod
    def is_moderator(user: discord.User | discord.Member) -> bool:
        """True if the user holds one of the configured moderator/admin roles."""
        mod_role_ids = set(env.PLAYTEST_COG_SETTINGS.MOD_ROLE_IDS)
        roles = getattr(user, "roles", [])
        return any(role.id in mod_role_ids for role in roles)

    @app_commands.command(
        name="update-playtest", description="Update the playtest menu message"
    )
    async def update_playtest(
        self, interaction: discord.Interaction
    ) -> Message | None:
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
        if not (is_scheduler or self.is_moderator(interaction.user)):
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PlaytestCog(bot))
