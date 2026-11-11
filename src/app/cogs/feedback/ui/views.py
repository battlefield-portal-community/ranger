"""The feedback intake views: the persistent menu and the duplicate prompt."""

from __future__ import annotations

import logging

import discord

from .... import db
from .. import dedupe
from .. import settings as feedback_settings
from . import modals

log = logging.getLogger(__name__)

BUG_BUTTON_ID = "feedback:bug"
FEATURE_BUTTON_ID = "feedback:feature"


class FeedbackMenuView(discord.ui.View):
    """The two buttons under the intake message, re-registered on every start."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Report a Bug",
        style=discord.ButtonStyle.danger,
        emoji="🐞",
        custom_id=BUG_BUTTON_ID,
    )
    async def report_bug(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._send_modal(interaction, "bug")

    @discord.ui.button(
        label="Request a Feature",
        style=discord.ButtonStyle.success,
        emoji="💡",
        custom_id=FEATURE_BUTTON_ID,
    )
    async def request_feature(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._send_modal(interaction, "feature")

    async def _send_modal(self, interaction: discord.Interaction, kind: str) -> None:
        config = feedback_settings.settings()
        forum_id = config.BUG_FORUM_ID if kind == "bug" else config.FEATURE_FORUM_ID
        forum = interaction.guild.get_channel(forum_id) if interaction.guild else None
        if forum is None:
            try:
                forum = await interaction.client.fetch_channel(forum_id)
            except discord.HTTPException:
                log.exception("Couldn't fetch the %s feedback forum", kind)
        if not isinstance(forum, discord.ForumChannel):
            await interaction.response.send_message(
                "The feedback forum is unreachable; ping a mod.", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            modals.build_modal(
                kind, forum, filesize_mb=interaction.filesize_limit // 2**20
            )
        )


class DuplicateMatchView(discord.ui.View):
    """Ephemeral prompt offering the existing threads, or filing anyway."""

    def __init__(self, matches: list[db.FeedbackPost], guild_id: int | None) -> None:
        super().__init__(timeout=dedupe.PENDING_TTL)
        for index, post in enumerate(matches, start=1):
            label = "Open existing" if len(matches) == 1 else f"Open existing #{index}"
            self.add_item(
                discord.ui.Button(
                    style=discord.ButtonStyle.link,
                    label=label,
                    url=f"https://discord.com/channels/{guild_id or '@me'}/{post.thread_id}",
                )
            )
        # Added here rather than with a decorator so it sits after the links.
        file_anyway = discord.ui.Button(
            label="File anyway", style=discord.ButtonStyle.secondary
        )
        file_anyway.callback = self._file_anyway
        self.add_item(file_anyway)

    async def _file_anyway(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        submission = dedupe.take(interaction.user.id)
        if not isinstance(submission, modals.Submission):
            await interaction.response.edit_message(
                content="That prompt expired; submit the report again.", view=None
            )
            return
        await interaction.response.edit_message(
            content="Filing this as a new post…", view=None
        )
        await modals.file_post(interaction, submission, force=True)
