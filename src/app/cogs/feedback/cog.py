"""The feedback cog: the intake menu message and the thread tag mirror."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from ... import db
from . import forms, tags
from . import settings as feedback_settings
from .ui import FeedbackMenuView

log = logging.getLogger(__name__)

MENU_STATE_KEY = "feedback_menu_message_id"

# Where a status change with no staff member to attribute is recorded.
MIRROR_ACTOR = "ranger"


class FeedbackCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._menu_ensured = False

    async def cog_load(self) -> None:
        if feedback_settings.configured() is None:
            log.info(
                "The feedback cog is inert: FEEDBACK_COG_SETTINGS__MENU_CHANNEL_ID "
                "is not set"
            )
            return
        # Re-register the persistent view so the buttons keep working after a restart.
        self.bot.add_view(FeedbackMenuView())
        for kind in ("bug", "feature"):
            if not forms.limits_fit(kind):
                log.error(
                    "The %s form no longer fits in a %s-character post; check "
                    "the field limits in forms.FORMS",
                    kind,
                    forms.DISCORD_MESSAGE_LIMIT,
                )

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if feedback_settings.configured() is None or self._menu_ensured:
            return
        self._menu_ensured = True
        try:
            await self.ensure_menu_message()
            self.report_forum_tags()
        except Exception:
            self._menu_ensured = False
            log.exception("Failed to ensure the feedback menu message")

    @commands.Cog.listener()
    async def on_thread_update(
        self, before: discord.Thread, after: discord.Thread
    ) -> None:
        config = feedback_settings.configured()
        if config is None:
            return
        parent = after.parent
        if parent is None or parent.id not in (
            config.BUG_FORUM_ID,
            config.FEATURE_FORUM_ID,
        ):
            return
        await self.sync_status(after)

    async def sync_status(self, thread: discord.Thread) -> None:
        """Mirror the thread's status tag into SQLite, if it changed.

        Best-effort by design: a retag made while the bot is down is missed, because
        Discord's own tags stay the truth and the later cleanup pass reads those.
        """
        post = await db.get_feedback(thread.id)
        if post is None:
            return
        status = tags.status_from_tags(thread.applied_tags)
        if status == post.status:
            return
        await db.set_feedback_status(thread.id, status)
        await db.log_feedback_event(
            thread.id, "status", MIRROR_ACTOR, f"{post.status} -> {status}"
        )
        log.info(
            "Feedback thread %s moved from %s to %s", thread.id, post.status, status
        )

    def report_forum_tags(self) -> None:
        """Log each forum's real tags, so a rename is visible instead of silent."""
        config = feedback_settings.settings()
        for forum_id in (config.BUG_FORUM_ID, config.FEATURE_FORUM_ID):
            forum = self.bot.get_channel(forum_id)
            if isinstance(forum, discord.ForumChannel):
                log.info(tags.tag_report(forum))
            else:
                log.warning("Feedback forum %s is not in the channel cache", forum_id)

    async def ensure_menu_message(self) -> None:
        """Post the intake menu once, or edit the stored one on restart."""
        channel_id = feedback_settings.settings().MENU_CHANNEL_ID
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(
            channel_id
        )
        if not isinstance(channel, discord.TextChannel):
            log.error("Feedback menu channel %s is not a text channel", channel_id)
            return

        # on_ready is the only caller, so the bot already knows its own user.
        bot_user = self.bot.user
        mention = bot_user.mention if bot_user is not None else "This bot"
        embed = discord.Embed(
            title="📮 Submit Feedback",
            description=(
                f"Press a button and fill in the form. {mention} will file your post "
                "in the right forum with the right tags and answer with a link.\n"
                "Search the forum first: there may already be an open bug report or "
                "feature request for it.\n"
                "A moderator replies in that thread, so keep an eye on it."
            ),
            color=discord.Color.blurple(),
        )
        view = FeedbackMenuView()
        # The bot names itself; nobody needs pinging, least of all itself, and the
        # message is edited on every restart.
        no_pings = discord.AllowedMentions.none()

        stored = await db.get_state(MENU_STATE_KEY)
        if stored:
            try:
                message = await channel.fetch_message(int(stored))
                await message.edit(embed=embed, view=view, allowed_mentions=no_pings)
                log.info("Refreshed the feedback menu message %s", stored)
                return
            except discord.NotFound:
                log.info(
                    "Stored feedback menu message %s is gone; posting a new one", stored
                )

        message = await channel.send(embed=embed, view=view, allowed_mentions=no_pings)
        await db.set_state(MENU_STATE_KEY, str(message.id))
        log.info("Posted the feedback menu message %s", message.id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FeedbackCog(bot))
