"""Playtest scheduling.

Users open a single modal (from a persistent "Schedule Playtest" button or the
``/schedule-playtest`` command), fill in a description, an optional experience
code and the regions to ping, and the bot posts an announcement that pings the
selected region roles and opens a thread on it. Each user's region selection is
remembered and pre-filled next time.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from .. import db
from ..config import env, load_regions

log = logging.getLogger(__name__)

MENU_BUTTON_CUSTOM_ID = "playtest:schedule"
MENU_STATE_KEY = "menu_message_id"


class PlaytestModal(discord.ui.Modal):
    """One modal capturing description, experience code and regions (in that order)."""

    def __init__(self, regions: dict[str, int], saved: list[str]) -> None:
        super().__init__(title="Schedule a Playtest")
        self._regions = regions

        self.description_input = discord.ui.TextInput(
            style=discord.TextStyle.paragraph,
            placeholder="What are we testing? Paste any video link here too.",
            required=True,
            max_length=2000,
        )
        self.code_input = discord.ui.TextInput(
            style=discord.TextStyle.short,
            placeholder="e.g. AB12CD",
            required=False,
            max_length=32,
        )
        options = [
            discord.SelectOption(label=name, value=name, default=name in saved)
            for name in regions
        ]
        self.region_select = discord.ui.Select(
            placeholder="Select region(s) to ping",
            options=options,
            min_values=1,
            max_values=len(options),
            required=True,
        )

        # Order: Description, Experience Code, Regions.
        self.add_item(
            discord.ui.Label(text="Playtest Description", component=self.description_input)
        )
        self.add_item(
            discord.ui.Label(
                text="Experience Code",
                description="Optional short code used to host the server.",
                component=self.code_input,
            )
        )
        self.add_item(discord.ui.Label(text="Regions to ping", component=self.region_select))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        selected = list(self.region_select.values)
        description = self.description_input.value.strip()
        code = self.code_input.value.strip()

        await db.set_user_regions(interaction.user.id, selected)

        guild = interaction.guild
        roles: list[discord.Role] = []
        missing: list[str] = []
        for key in selected:
            role_id = self._regions.get(key)
            role = guild.get_role(role_id) if guild and role_id else None
            if role is not None:
                roles.append(role)
            else:
                missing.append(key)
                log.warning("Region role missing for %r (id=%s)", key, role_id)

        embed = discord.Embed(
            title=f"🎮 Playtest: {code}" if code else "🎮 New Playtest",
            description=description,
            color=discord.Color.green(),
        )
        if code:
            embed.add_field(name="Experience Code", value=f"`{code}`", inline=True)
        embed.add_field(name="Regions", value=", ".join(selected), inline=True)
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url,
        )

        channel_id = env.PLAYTEST_COG_SETTINGS.announce_channel_id
        channel = interaction.client.get_channel(channel_id) or await interaction.client.fetch_channel(
            channel_id
        )

        message = await channel.send(
            content=" ".join(r.mention for r in roles) or None,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(roles=roles or False),
        )
        thread_name = (f"Playtest {code}" if code else f"Playtest by {interaction.user.display_name}")[
            :100
        ]
        await message.create_thread(name=thread_name)

        note = f"\n⚠️ Couldn't find role(s) for: {', '.join(missing)}" if missing else ""
        await interaction.response.send_message(
            f"✅ Scheduled in {channel.mention}!{note}", ephemeral=True
        )


def build_playtest_modal(saved: list[str]) -> PlaytestModal:
    """Build the modal with the region select pre-filled from saved prefs."""
    return PlaytestModal(load_regions(), saved)


class PlaytestMenuView(discord.ui.View):
    """Persistent view holding the menu button."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Schedule Playtest",
        style=discord.ButtonStyle.success,
        emoji="🗓️",
        custom_id=MENU_BUTTON_CUSTOM_ID,
    )
    async def schedule(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        saved = await db.get_user_regions(interaction.user.id)
        await interaction.response.send_modal(build_playtest_modal(saved))


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

    async def ensure_menu_message(self) -> None:
        """Post the menu message once, or edit the existing one on restart."""
        channel_id = env.PLAYTEST_COG_SETTINGS.menu_channel_id
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)

        embed = discord.Embed(
            title="🎮 Playtest Scheduler",
            description=(
                "Click the button below to schedule a new playtest session.\n"
                "You'll add a description and choose the regions to ping."
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
