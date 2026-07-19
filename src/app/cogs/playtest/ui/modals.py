"""Playtest modals: the schedule / update forms shown to users.

A shared :class:`PlaytestModal` base builds the description, experience code and
region inputs; :class:`NewPlaytestModal` and :class:`UpdatePlaytestModal`
implement the "schedule" and "edit" submit flows respectively.
"""

from __future__ import annotations

import logging

import discord

from .... import db
from ....config import load_regions
from ..announcements import (
    get_announcement_channel,
    send_announcement,
    update_announcement,
)

log = logging.getLogger(__name__)


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
