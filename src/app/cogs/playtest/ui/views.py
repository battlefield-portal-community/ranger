"""Persistent view holding the playtest menu button."""

from __future__ import annotations

import discord

from .... import db
from .modals import build_playtest_modal

MENU_BUTTON_CUSTOM_ID = "playtest:schedule"


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
