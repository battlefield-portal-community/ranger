"""Playtest modals: the schedule / update forms shown to users.

A shared :class:`PlaytestModal` base builds the description, experience code,
playtest time and region inputs; :class:`NewPlaytestModal` and
:class:`UpdatePlaytestModal` implement the "schedule" and "edit" submit flows
respectively.
"""

from __future__ import annotations

import asyncio
import logging

import discord

from .... import db
from ....config import env, load_regions
from .. import events
from ..announcements import (
    EXPERIENCE_CODE_MAX_LENGTH,
    description_char_budget,
    get_announcement_channel,
    send_announcement,
    update_announcement,
)
from ..experience import post_experience_embed

log = logging.getLogger(__name__)

# Name of the slash command users run inside a thread to edit their playtest.
# Defined in the cog; kept as a literal here to avoid a circular import.
UPDATE_COMMAND_NAME = "update-playtest"

_EVENT_HINT = "check the event channel setting and my Manage Events permission."
EVENT_FAILED_NOTE = f"\n⚠️ Couldn't create the voice event — {_EVENT_HINT}"
EVENT_SYNC_FAILED_NOTE = f"\n⚠️ Couldn't update the voice event — {_EVENT_HINT}"

background_tasks: set[asyncio.Task] = set()


def spawn_task(coro) -> None:
    """Run a coroutine as a tracked fire-and-forget background task."""
    task = asyncio.create_task(coro)
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


async def _command_mention(interaction: discord.Interaction, name: str) -> str:
    """Return a clickable command mention (``</name:id>``), or ``/name`` on failure."""
    try:
        commands = await interaction.client.tree.fetch_commands(guild=interaction.guild)
    except discord.HTTPException:
        log.warning("Couldn't fetch commands to mention %r", name)
        return f"/{name}"
    for command in commands:
        if command.name == name:
            return command.mention
    return f"/{name}"


async def _delete_pin_notification(thread: discord.Thread) -> None:
    """Remove the "pinned a message" system message Discord posts when we pin."""
    async for message in thread.history(limit=5):
        if message.type is discord.MessageType.pins_add:
            try:
                await message.delete()
            except discord.HTTPException:
                log.warning("Failed to delete pin notification in thread %s", thread.id)
            return


class PlaytestModal(discord.ui.Modal):
    """Base modal capturing description, code, time and regions (in that order).

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

        # Cap the description so the assembled announcement can't exceed
        # Discord's message limit once the header, code, regions and footer are
        # added — otherwise the send/edit fails with a 400.
        description_limit = description_char_budget(regions.values())
        self.description_input = discord.ui.TextInput(
            style=discord.TextStyle.paragraph,
            placeholder="What are we testing? Paste any video link here too.",
            required=True,
            max_length=description_limit,
        )

        self.code_input = discord.ui.TextInput(
            style=discord.TextStyle.short,
            placeholder="e.g. AB12CD",
            required=False,
            max_length=EXPERIENCE_CODE_MAX_LENGTH,
        )

        self.time_input = discord.ui.TextInput(
            style=discord.TextStyle.short,
            placeholder="e.g. <t:1785688200:F> — from discordtimestamps.com",
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

        # Order: Description, Experience Code, Playtest Time, Regions.
        self.add_item(
            discord.ui.Label(
                text="Playtest Description",
                description=f"Markdown is supported. Max {description_limit} characters.",
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
                text="Playtest Time",
                description=(
                    "**Optional.** Paste a Discord timestamp; "
                    "a voice event will be created."
                ),
                component=self.time_input,
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

    def _read_inputs(self) -> tuple[list[str], str, str, str]:
        """Pull the selection, description, code and raw time off the modal.

        The time is returned unparsed so each flow can surface a parse error in
        the way that suits it.
        """
        return (
            list(self.region_select.values),
            self.description_input.value.strip(),
            self.code_input.value.strip().upper(),
            self.time_input.value.strip(),
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raise NotImplementedError


class NewPlaytestModal(PlaytestModal):
    """Modal for scheduling a brand new playtest."""

    modal_title = "Schedule a Playtest"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        selected, description, code, raw_time = self._read_inputs()

        # Validate the time before deferring so a bad one is a plain ephemeral
        # error with nothing created.
        try:
            scheduled_at = events.parse_playtest_time(raw_time)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)

        # Posting the announcement, thread and pin takes longer than the 3s
        # interaction window, so acknowledge first and reply via followup.
        await interaction.response.defer(ephemeral=True)

        await db.set_user_regions(interaction.user.id, selected)

        roles, missing = self._resolve_roles(interaction.guild, selected)

        channel = await get_announcement_channel(interaction.guild)

        if channel is None:
            await interaction.followup.send(
                "Couldn't find the announcement channel. Please contact an admin.",
                ephemeral=True,
            )
            return

        message = await send_announcement(
            interaction.user.id, channel, roles, description, code, scheduled_at
        )
        thread_name = (
            f"Playtest {code}"
            if code
            else f"Playtest by {interaction.user.display_name}"
        )[:100]
        thread: discord.Thread = await message.create_thread(name=thread_name)
        mention = await _command_mention(interaction, UPDATE_COMMAND_NAME)
        first_message = await thread.send(f"Use {mention} to update the playtest.")
        await first_message.pin()
        await _delete_pin_notification(thread)
        await db.set_playtest(
            user_id=interaction.user.id,
            message_id=thread.id,
            regions=selected,
            description=description,
            code=code,
            scheduled_at=scheduled_at,
        )

        note = f"\n⚠️ Couldn't find role(s) for: {', '.join(missing)}" if missing else ""
        if scheduled_at:
            note += await self._create_event(
                interaction, thread, thread_name, description, scheduled_at
            )
        await interaction.followup.send(
            f"✅ Playtest Scheduled, Thread: {thread.mention}!{note}", ephemeral=True
        )

        # The experience lookup hits the network and can be slow, so run it after
        # the scheduling flow has fully finished rather than blocking on_submit.
        if code:
            spawn_task(post_experience_embed(thread, code))

    @staticmethod
    async def _create_event(
        interaction: discord.Interaction,
        thread: discord.Thread,
        name: str,
        description: str,
        scheduled_at: int,
    ) -> str:
        """Create the voice event for a new playtest, returning any warning note."""
        event = await events.create_playtest_event(
            interaction.guild, name=name, start_at=scheduled_at, description=description
        )
        if event is None:
            return EVENT_FAILED_NOTE
        duration = env.PLAYTEST_COG_SETTINGS.EVENT_DEFAULT_DURATION_MINUTES * 60
        await db.update_playtest_event(
            thread.id, event_id=str(event.id), ends_at=scheduled_at + duration
        )
        await events.post_event_link(thread, event.guild_id, event.id)
        return ""


class UpdatePlaytestModal(PlaytestModal):
    """Modal for editing an already-scheduled playtest and its announcement."""

    modal_title = "Update Playtest"

    def __init__(
        self,
        regions: dict[str, int],
        selected_regions: list[str],
        message: discord.Message,
        playtest: db.Playtest,
    ) -> None:
        super().__init__(regions, selected_regions)
        self.description_input.default = playtest.description
        self.code_input.default = playtest.code
        if playtest.scheduled_at:
            self.time_input.default = f"<t:{playtest.scheduled_at}:F>"
        self._message = message
        self._playtest = playtest
        self._scheduler_id = int(playtest.user_id)

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
            playtest=playtest,
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        selected, description, code, raw_time = self._read_inputs()

        # Validate the time before deferring so a bad one changes nothing.
        try:
            scheduled_at = events.parse_playtest_time(raw_time)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)

        # Editing the announcement can exceed the 3s interaction window, so
        # acknowledge first and reply via followup.
        await interaction.response.defer(ephemeral=True)

        roles, missing = self._resolve_roles(interaction.guild, selected)

        await update_announcement(
            self._scheduler_id, self._message, roles, description, code, scheduled_at
        )
        await db.set_playtest(
            user_id=self._scheduler_id,
            message_id=self._message.id,
            regions=selected,
            description=description,
            code=code,
            scheduled_at=scheduled_at,
        )

        event_id, ends_at = await events.sync_playtest_event(
            interaction.guild,
            interaction.channel,
            self._playtest,
            new_scheduled_at=scheduled_at,
            name=interaction.channel.name,
            description=description,
        )
        # Only write when the event actually moved, so an ordinary description
        # edit doesn't reset the end warning.
        if (event_id, ends_at) != (self._playtest.event_id, self._playtest.ends_at):
            await db.update_playtest_event(
                self._message.id, event_id=event_id, ends_at=ends_at
            )

        note = f"\n⚠️ Couldn't find role(s) for: {', '.join(missing)}" if missing else ""
        if scheduled_at and event_id is None:
            note += EVENT_SYNC_FAILED_NOTE
        await interaction.followup.send(f"✅ Playtest updated!{note}", ephemeral=True)


def build_playtest_modal(saved: list[str]) -> NewPlaytestModal:
    """Build the new-playtest modal with regions pre-filled from saved prefs."""
    return NewPlaytestModal(load_regions(), saved)
