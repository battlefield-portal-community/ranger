import json
import asyncio
from itertools import zip_longest


import discord
from discord.ext import tasks, commands
from loguru import logger

from .cog_base import CogBase
from ..utils.helper import project_base_path, MAIN_GUILD_ID

from ..bot import Ranger


class ForumAnalyser(CogBase):
    def __init__(self, bot_: Ranger):
        self.bot = bot_
        self.guild = None
        self.forum_channel: discord.ForumChannel | None = None
        self.target_channel: discord.TextChannel | None = None
        self.threads = []

    @commands.slash_command(
        name="sort_data",
        description="Update the data",
        guild_ids=[MAIN_GUILD_ID],
        guild_only=True,
    )
    @discord.default_permissions(
        administrator=True,
    )
    async def sort_data(self, ctx: discord.ApplicationContext):
        if self.guild is None:
            self.guild = ctx.guild
            self.forum_channel = self.guild.get_channel(1006491137441276005)
            self.target_channel = self.guild.get_channel(1152930428714483813)

        if ctx.channel != self.target_channel:
            return await ctx.respond(f"Can only be used in <#{self.target_channel}>")

        interaction = await ctx.respond('Generating data...')
        asyncio.create_task(self.generate_data(interaction))
        return

    async def generate_data(self, interaction: discord.Interaction):
        self.threads = self.forum_channel.threads
        async for thread in self.forum_channel.archived_threads(limit=None):
            self.threads.append(thread)
        await interaction.edit_original_response(content=f"Got {len(self.threads)} threads")

        latest_thread = self.threads[0]
        if latest_thread.is_pinned():
            latest_thread = self.threads[1]

        stats = [
            f"> Stats :",
            f"> Total Threads : {len(self.threads)}",
            f"> Latest Thread : {latest_thread.mention}",
            f"> First Thread : {self.threads[-1].mention}",
        ]
        await self.target_channel.send("\n".join(stats))
        # filter for "bug report : "
        bug_report_msg = await self.target_channel.send(content=f"Generating bug report stats...")
        threads_processed = 0
        TOP_X_LIMIT = 10
        bugs = [
            thread for thread in self.threads if is_valid_bug_thread(thread)
        ]
        bug_thread: discord.Thread
        reaction_counts = []
        for bug_thread in bugs:
            starter = bug_thread.starting_message
            if starter is None:
                msg_list = (await bug_thread.history(limit=1, oldest_first=True).flatten())
                if len(msg_list):
                    starter = msg_list[0]
                else:
                    logger.warning(f"Thread {bug_thread.name}:{bug_thread.id} has no starting message")
                    continue
            if len(starter.reactions):
                # add thread if it has good activity
                if (reaction_count := starter.reactions[0].count) > 5 or bug_thread.message_count > 30:

                    reaction_counts.append((reaction_count, bug_thread))
            else:
                logger.trace(f"Thread {bug_thread.name}:{bug_thread.id} has no reactions")
            threads_processed += 1
            if threads_processed % 10 == 0:
                await bug_report_msg.edit(
                    content=f"Generating bug report stats...Processed {threads_processed}/{len(bugs)} threads"
                )
        reaction_counts.sort(key=lambda x: x[0], reverse=True)
        stats = [
            f"> # Top threads for bugs :",
            "**(filtered by reaction > 5 OR messages > 30)**",
            *[
                f"> {thread.mention} : {count} upvotes and {thread.message_count} messages"
                for count, thread in reaction_counts
            ],
        ]
        await bug_report_msg.edit(content="\n".join(stats))


def is_valid_bug_thread(thread: discord.Thread):
    BUG_TAG_ID = 1006563163925397640
    PATCHED_TAG_ID = 1009125563295871117
    PATCHED_EMOJI_ID = None  # todo: get emoji id
    if thread.locked or has_tag(thread, PATCHED_TAG_ID) or thread.is_pinned():
        return False
    if has_tag(thread, BUG_TAG_ID):
        return True
    return False


def has_tag(thread: discord.Thread, tag_id: int):
    return tag_id in [tag.id for tag in thread.applied_tags]


def setup(bot: Ranger):
    bot.add_cog(ForumAnalyser(bot))
