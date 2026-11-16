"""The feedback cog: the intake menu message, ``/update-feedback`` and the tag
mirror."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ... import db, permissions
from . import forms, tags
from . import settings as feedback_settings
from .ui import FeedbackMenuView, UpdateFeedbackModal, menu_colour

log = logging.getLogger(__name__)

MENU_STATE_KEY = "feedback_menu_message_id"

# Where a status change with no staff member to attribute is recorded.
MIRROR_ACTOR = "ranger"


class FeedbackCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._menu_ensured = False
        # Position in MENU_COLOURS: 0 on every start, so the first paint is blurple.
        self._menu_colour = 0

    async def cog_unload(self) -> None:
        self.cycle_menu_colour.cancel()

    async def cog_load(self) -> None:
        if feedback_settings.configured() is None:
            log.info(
                "The feedback cog is inert: FEEDBACK_COG_SETTINGS__MENU_CHANNEL_ID "
                "is not set"
            )
            return
        # Re-register the persistent view so the buttons keep working after a
        # restart. They are section accessories in the v2 layout, and those are
        # dispatched the same way as any other persistent button.
        self.bot.add_view(FeedbackMenuView())
        for kind in ("bug", "feature"):
            if not forms.limits_fit(kind):
                log.error(
                    "The %s form no longer fits in a %s-character post; check "
                    "the field limits in forms.FORMS",
                    kind,
                    forms.DISCORD_MESSAGE_LIMIT,
                )
        cycle = feedback_settings.settings().MENU_COLOUR_CYCLE_SECONDS
        if cycle > 0:
            self.cycle_menu_colour.change_interval(seconds=cycle)
            self.cycle_menu_colour.start()

    @tasks.loop(minutes=5)
    async def cycle_menu_colour(self) -> None:
        """Repaint the menu with the next accent colour.

        The colour lives in the message payload, so a change costs one edit. The
        interval comes from settings (``change_interval`` in ``cog_load``); a failed
        repaint is logged rather than killing the loop, and the next tick retries.
        """
        self._menu_colour += 1
        try:
            await self.ensure_menu_message()
        except Exception:
            log.exception("Failed to repaint the feedback menu message")

    @cycle_menu_colour.before_loop
    async def before_cycle_menu_colour(self) -> None:
        # The first tick is one interval after ready, so the menu on_ready posts is
        # the one the cycle edits.
        await self.wait_until_ready()

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
        forums = (
            ("bug", config.BUG_FORUM_ID),
            ("feature", config.FEATURE_FORUM_ID),
        )
        for kind, forum_id in forums:
            forum = self.bot.get_channel(forum_id)
            if isinstance(forum, discord.ForumChannel):
                log.info(tags.tag_report(forum, kind))
            else:
                log.warning("Feedback forum %s is not in the channel cache", forum_id)

    @app_commands.command(
        name="update-feedback",
        description="Update the feedback post this thread was started with",
    )
    async def update_feedback(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.Thread):
            await interaction.response.send_message(
                "This command can only be used in a thread", ephemeral=True
            )
            return

        config = feedback_settings.configured()
        if config is None:
            await interaction.response.send_message(
                "The feedback cog is not configured; ping a mod.", ephemeral=True
            )
            return

        parent = channel.parent
        if parent is None or parent.id not in (
            config.BUG_FORUM_ID,
            config.FEATURE_FORUM_ID,
        ):
            await interaction.response.send_message(
                "This thread is not a feedback thread", ephemeral=True
            )
            return

        post = await db.get_feedback(channel.id)
        if post is None:
            await interaction.response.send_message(
                "This post wasn't filed by Ranger", ephemeral=True
            )
            return

        # A bug post is edited in the bug forum and a feature post in the feature
        # forum, never one from the other.
        if not isinstance(parent, discord.ForumChannel) or parent.id != post.forum_id:
            await interaction.response.send_message(
                "This post belongs in another forum", ephemeral=True
            )
            return

        # A forum post's starter message shares its id with the thread.
        try:
            starter = await channel.fetch_message(channel.id)
        except discord.NotFound:
            log.warning("Starter message for feedback thread %s not found", channel.id)
            await interaction.response.send_message(
                "Post message not found", ephemeral=True
            )
            return
        except discord.Forbidden:
            log.warning("Not allowed to read feedback thread %s", channel.id)
            await interaction.response.send_message(
                "I don't have permission to read that post", ephemeral=True
            )
            return
        except discord.HTTPException:
            log.exception("Failed to fetch feedback post %s", channel.id)
            await interaction.response.send_message(
                "Failed to fetch that post", ephemeral=True
            )
            return

        # Only posts Ranger itself started may be edited, whatever the row says.
        if self.bot.user is None or starter.author.id != self.bot.user.id:
            await interaction.response.send_message(
                "This thread was not started by Ranger", ephemeral=True
            )
            return

        # Only the original reporter or a moderator may update the post.
        is_reporter = str(interaction.user.id) == post.reporter_id
        if not (is_reporter or permissions.is_moderator(interaction.user)):
            await interaction.response.send_message(
                "Only the post's reporter or a moderator can update it", ephemeral=True
            )
            return

        await interaction.response.send_modal(
            UpdateFeedbackModal(post, parent, channel, starter)
        )

    async def ensure_menu_message(self) -> None:
        """Post the intake menu, edit the stored one, or repaint it on the cycle."""
        channel_id = feedback_settings.settings().MENU_CHANNEL_ID
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(
            channel_id
        )
        if not isinstance(channel, discord.TextChannel):
            log.error("Feedback menu channel %s is not a text channel", channel_id)
            return

        # The menu is a components v2 layout, so it carries no embed and no
        # content: the title is a text display inside the container. on_ready is the
        # only caller, so the bot already knows its own user by now.
        bot_user = self.bot.user
        mention = bot_user.mention if bot_user is not None else "The bot"
        view = FeedbackMenuView(
            bot_mention=mention, accent=menu_colour(self._menu_colour)
        )
        # Nobody needs pinging, least of all the bot named in the footer, and the
        # message is edited on every restart.
        no_pings = discord.AllowedMentions.none()

        stored = await db.get_state(MENU_STATE_KEY)
        if stored:
            try:
                message = await channel.fetch_message(int(stored))
                # content and embed are passed explicitly: a v2 message can carry
                # neither, so the old embed has to go in the same edit that turns
                # this message into a layout.
                await message.edit(
                    content=None,
                    embed=None,
                    view=view,
                    allowed_mentions=no_pings,
                )
                log.info("Refreshed the feedback menu message %s", stored)
                return
            except discord.NotFound:
                log.info(
                    "Stored feedback menu message %s is gone; posting a new one", stored
                )

        message = await channel.send(view=view, allowed_mentions=no_pings)
        await db.set_state(MENU_STATE_KEY, str(message.id))
        log.info("Posted the feedback menu message %s", message.id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FeedbackCog(bot))
