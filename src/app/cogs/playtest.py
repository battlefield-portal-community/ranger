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
from discord import app_commands, TextChannel, Message
from discord.ext import commands

from .. import db
from ..config import env, load_regions

log = logging.getLogger(__name__)

MENU_BUTTON_CUSTOM_ID = "playtest:schedule"
MENU_STATE_KEY = "menu_message_id"


async def get_announcement_channel(guild: discord.Guild | None) -> TextChannel | None:
    if not guild:
        return None
    try:
        channel_id = env.PLAYTEST_COG_SETTINGS.ANNOUNCE_CHANNEL_ID
        channel = guild.get_channel(channel_id) or await guild.fetch_channel(channel_id)
        assert isinstance(channel, TextChannel)
        return channel
    except AssertionError:
        log.exception("Announcement channel is not a TextChannel")

    return None


async def get_announcement_message(
    guild: discord.Guild | None, message_id: int
) -> discord.Message | None: ...


async def build_announcement_message(
    user_id: int,
    description: str,
    code: str,
    roles: list[discord.Role],
) -> list[str]:
    lines = [
        "# 🎮 New Playtest",
        f"Scheduled by **<@{user_id}>**",
        "",
        description,
        "",
    ]
    if code:
        lines.append(f"**Experience Code:** `{code}`")
    lines.append(f"**Regions:** {' '.join(r.mention for r in roles) or '—'}")

    return lines


async def send_announcement(
    user_id: int,
    channel: discord.abc.Messageable,
    roles: list[discord.Role],
    description: str,
    code: str,
) -> discord.Message:
    """Post the announcement as a plain text message (no embed)."""
    message = await build_announcement_message(user_id, description, code, roles)
    return await channel.send(
        content="\n".join(message),
        allowed_mentions=discord.AllowedMentions(roles=roles or False),
    )


async def update_announcement(
    user_id: int,
    message: discord.Message,
    roles: list[discord.Role],
    description: str,
    code: str,
) -> None:
    """Edit the announcement to include the new details."""

    lines = await build_announcement_message(user_id, description, code, roles)
    await message.edit(
        content="\n".join(lines),
        allowed_mentions=discord.AllowedMentions(roles=roles or False),
    )


class PlaytestModal(discord.ui.Modal):
    """Base modal capturing description, experience code and regions (in that order).

    Subclasses set :attr:`modal_title` and implement :meth:`on_submit` for the
    "new" and "update" flows respectively.
    """

    modal_title = "Playtest"

    def __init__(
        self,
        regions: dict[str, int],
        selected_regions: list[str],
    ) -> None:
        super().__init__(title=self.modal_title)
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
            discord.SelectOption(
                label=name, value=name, default=name in selected_regions
            )
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
            discord.ui.Label(
                text="Playtest Description",
                description="Markdown is supported.",
                component=self.description_input,
            )
        )
        self.add_item(
            discord.ui.Label(
                text="Experience Code",
                description="**Optional** short code used to host the server.",
                component=self.code_input,
            )
        )
        self.add_item(
            discord.ui.Label(
                text="Regions to ping",
                description="Selection is saved for next time.",
                component=self.region_select,
            )
        )

    def _resolve_roles(
        self, guild: discord.Guild | None, selected: list[str]
    ) -> tuple[list[discord.Role], list[str]]:
        """Map selected region keys to roles, collecting any that can't be found."""
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
        return roles, missing

    def _read_inputs(self) -> tuple[list[str], str, str]:
        """Pull the current selection, description and code off the modal."""
        return (
            list(self.region_select.values),
            self.description_input.value.strip(),
            self.code_input.value.strip(),
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raise NotImplementedError


class NewPlaytestModal(PlaytestModal):
    """Modal for scheduling a brand new playtest."""

    modal_title = "Schedule a Playtest"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        selected, description, code = self._read_inputs()

        await db.set_user_regions(interaction.user.id, selected)

        roles, missing = self._resolve_roles(interaction.guild, selected)

        channel = await get_announcement_channel(interaction.guild)

        if channel is None:
            await interaction.response.send_message(
                "Couldn't find the announcement channel. Please contact an admin.",
                ephemeral=True,
            )
            return

        message = await send_announcement(
            interaction.user.id, channel, roles, description, code
        )
        thread_name = (
            f"Playtest {code}"
            if code
            else f"Playtest by {interaction.user.display_name}"
        )[:100]
        thread: discord.Thread = await message.create_thread(name=thread_name)
        first_message = await thread.send(
            "use /update-playtest command to update the playtest"
        )
        await first_message.pin()
        note = f"\n⚠️ Couldn't find role(s) for: {', '.join(missing)}" if missing else ""
        await interaction.response.send_message(
            f"✅ Playtest Scheduled, Thread: {thread.mention}!{note}", ephemeral=True
        )
        await db.set_playtest(
            user_id=interaction.user.id,
            message_id=thread.id,
            regions=selected,
            description=description,
            code=code,
        )


class UpdatePlaytestModal(PlaytestModal):
    """Modal for editing an already-scheduled playtest and its announcement."""

    modal_title = "Update Playtest"

    def __init__(
        self,
        regions: dict[str, int],
        selected_regions: list[str],
        message: discord.Message,
        scheduler_id: int,
        description: str,
        code: str,
    ) -> None:
        super().__init__(regions, selected_regions)
        self.description_input.default = description
        self.code_input.default = code
        self._message = message
        self._scheduler_id = scheduler_id

    @classmethod
    def from_playtest(
        cls, playtest: db.Playtest, message: discord.Message
    ) -> UpdatePlaytestModal:
        """Build the modal pre-filled from an already-fetched playtest record and
        its announcement message."""
        return cls(
            regions=load_regions(),
            selected_regions=playtest.regions,
            message=message,
            scheduler_id=int(playtest.user_id),
            description=playtest.description,
            code=playtest.code,
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        selected, description, code = self._read_inputs()

        roles, missing = self._resolve_roles(interaction.guild, selected)

        await update_announcement(
            self._scheduler_id, self._message, roles, description, code
        )
        await db.set_playtest(
            user_id=self._scheduler_id,
            message_id=self._message.id,
            regions=selected,
            description=description,
            code=code,
        )
        note = f"\n⚠️ Couldn't find role(s) for: {', '.join(missing)}" if missing else ""
        await interaction.response.send_message(
            f"✅ Playtest updated!{note}", ephemeral=True
        )


def build_playtest_modal(saved: list[str]) -> NewPlaytestModal:
    """Build the new-playtest modal with regions pre-filled from saved prefs."""
    return NewPlaytestModal(load_regions(), saved)


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

    @app_commands.command(
        name="update-playtest-message", description="Update the playtest menu message"
    )
    async def update_playtest_message(
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
