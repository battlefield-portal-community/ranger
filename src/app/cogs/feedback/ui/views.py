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

HEADER_TEXT = "## 📮 Submit Feedback"
# A section holds its text beside one accessory, so the question and the line under
# it are separate text displays with the button to their right.
FEATURE_QUESTION = "**Have an idea for maps, scripts, or the editor?**"
FEATURE_TEXT = "Say what you want and why."
BUG_QUESTION = "**Encountered something broken?**"
BUG_TEXT = "Tell us what happened, what you expected, and how to reproduce it."
# Subtext: small and grey, so it reads as a footnote rather than a third action. The
# mention is rendered with AllowedMentions.none(), so it names the bot without
# pinging it. A section needs an accessory, and this line has nothing to press.
FOOTER_TEXT = (
    "-# {mention} will open a new post in the matching forum and reply here with a "
    "link to it."
)


class FeedbackMenuView(discord.ui.LayoutView):
    """The intake menu: a title, then a question with its button beside it.

    A v2 layout rather than an embed, so the message can carry a header, dividers
    and one section per form with the button as its accessory. The rules section is
    planned for v1.1: prepend it here.
    """

    def __init__(self, *, bot_mention: str = "The bot") -> None:
        """`bot_mention` names who files the post; the persistent view registered at
        startup has no user yet, and only its button callbacks matter."""
        super().__init__(timeout=None)
        # Section accessories cannot use the @discord.ui.button decorator, which
        # only collects items at the top level of a layout view, so the buttons are
        # built here and their callbacks bound as instance attributes.
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(HEADER_TEXT),
                discord.ui.Separator(),
                discord.ui.Section(
                    discord.ui.TextDisplay(FEATURE_QUESTION),
                    discord.ui.TextDisplay(FEATURE_TEXT),
                    accessory=self._feature_button(),
                ),
                discord.ui.Separator(),
                discord.ui.Section(
                    discord.ui.TextDisplay(BUG_QUESTION),
                    discord.ui.TextDisplay(BUG_TEXT),
                    accessory=self._bug_button(),
                ),
                discord.ui.Separator(),
                discord.ui.TextDisplay(FOOTER_TEXT.format(mention=bot_mention)),
                accent_colour=discord.Color.blurple(),
            )
        )

    # Features sit first, matching the order they are added in.
    def _feature_button(self) -> discord.ui.Button:
        button = discord.ui.Button(
            label="Request a Feature",
            style=discord.ButtonStyle.success,
            emoji="💡",
            custom_id=FEATURE_BUTTON_ID,
        )
        button.callback = self._request_feature
        return button

    def _bug_button(self) -> discord.ui.Button:
        button = discord.ui.Button(
            label="Report a Bug",
            style=discord.ButtonStyle.secondary,
            emoji="🐞",
            custom_id=BUG_BUTTON_ID,
        )
        button.callback = self._report_bug
        return button

    async def _request_feature(self, interaction: discord.Interaction) -> None:
        await self._send_modal(interaction, "feature")

    async def _report_bug(self, interaction: discord.Interaction) -> None:
        await self._send_modal(interaction, "bug")

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

    async def _file_anyway(self, interaction: discord.Interaction) -> None:
        # An item callback takes the interaction alone; the button is not passed.
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
