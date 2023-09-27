import asyncio
import datetime
from zoneinfo import ZoneInfo
import discord
from discord.ext import commands
from discord import option
from loguru import logger

from .cog_base import CogBase
from ..utils.helper import MAIN_GUILD_ID

from ..bot import Ranger


class ForumAnalyser(CogBase):
    def __init__(self, bot_: Ranger):
        self.bot = bot_
        self.guild = None
        self.forum_channel: discord.ForumChannel | None = None
        self.target_channel: discord.TextChannel | None = None
        self.threads = []

    @commands.slash_command(
        name="kowalski_analysis",
        description="Analyse the forum for threads that meet a certain condition",
        guild_ids=[MAIN_GUILD_ID],
        guild_only=True,
    )
    @option(
        name="reaction count",
        description="The reaction count to filter by, defaults to 5",
        type=discord.SlashCommandOptionType.integer,
        required=False,
        default=5
    )
    @option(
        name="Message count",
        description=("The message count to filter by (only threads with more "
                     "than this amount of messages will be shown) defaults to 30"),
        type=discord.SlashCommandOptionType.integer,
        required=False,
        default=30
    )
    @option(
        name="condition",
        description="The condition to sort by",
        type=discord.SlashCommandOptionType.string,
        required=False,
        default=''
    )
    @option(
        name="use cache",
        description="Whether to use the cached data",
        type=discord.SlashCommandOptionType.boolean,
        required=False,
        default=True
    )
    @option(
        name="limit",
        description="The limit of threads to sort",
        type=discord.SlashCommandOptionType.integer,
        required=False,
        default=10
    )
    @discord.default_permissions(
        administrator=True,
    )
    async def kowalski_analysis(
            self,
            ctx: discord.ApplicationContext,
            reaction_count: int = 5,
            message_count: int = 30,
            condition: str = '',
            use_cache: bool = False,
            limit: int = 10

    ):
        if any([reaction_count < 0, message_count < 0, limit < 0]):
            return await ctx.respond(f"Invalid arguments, {reaction_count=}, {message_count=}, {limit=}")

        if self.guild is None:
            self.guild = ctx.guild
            self.forum_channel = self.guild.get_channel(1006491137441276005)
            self.target_channel = self.guild.get_channel(1152930428714483813)

        if ctx.channel != self.target_channel:
            return await ctx.respond(f"Can only be used in <#{self.target_channel}>")

        interaction = await ctx.respond('Generating data...')
        asyncio.create_task(self.generate_data(
            interaction,
            min_reaction_count=reaction_count,
            min_message_count=message_count,
            condition=condition,
            use_cache=use_cache,
            limit=limit
        )
        )
        return

    async def generate_data(
            self,
            interaction: discord.Interaction,
            min_reaction_count: int = 5,
            min_message_count: int = 30,
            condition: str = None,
            use_cache: bool = True,
            limit: int = 10
    ):
        if not self.threads or not use_cache:
            self.threads = self.forum_channel.threads
            async for thread in self.forum_channel.archived_threads(limit=None):
                self.threads.append(thread)
            await interaction.edit_original_response(content=f"Got {len(self.threads)} threads")

        # if the first thread is pinned, remove it
        self.threads = self.threads[1:] if self.threads[0].is_pinned() else self.threads

        stats = [
            f"> Stats :",
            f"> Total Threads : {len(self.threads)}",
            f"> Latest Thread : {self.threads[0].mention}",
            f"> First Thread : {self.threads[-1].mention}",
        ]
        await self.target_channel.send("\n".join(stats))
        # filter for "bug report : "
        bug_report_msg = await self.target_channel.send(content=f"Generating bug report stats...")
        threads_processed = 0
        bugs = [
            thread for thread in self.threads if is_valid_bug_thread(thread)
        ]
        await bug_report_msg.edit(content=f"Found {len(bugs)} threads that are bug reports")
        bug_thread: discord.Thread
        reaction_counts = []
        for bug_thread in bugs:
            if condition and not title_passes_condition(bug_thread.name, condition):
                logger.debug(f"Thread {bug_thread.name} failed {condition} condition")
                continue

            if (starter := bug_thread.starting_message) is None:
                msg_list = await bug_thread.history(limit=1, oldest_first=True).flatten()
                if len(msg_list):
                    starter = msg_list[0]
                else:
                    logger.warning(f"Thread {bug_thread.name}:{bug_thread.id} has no starting message")
                    continue
            if len(starter.reactions) and (reaction_count := starter.reactions[0].count) >= min_reaction_count:
                # add thread if it has good activity
                reaction_counts.append((reaction_count, bug_thread))
            elif bug_thread.message_count >= min_message_count:
                # add thread if it has a lot of messages
                reaction_counts.append((0, bug_thread))
            else:
                logger.trace(f"Thread {bug_thread.name}:{bug_thread.id} has no reactions")
            threads_processed += 1
            if threads_processed % 10 == 0:
                await bug_report_msg.edit(
                    content=f"Generating bug report stats...Processed {threads_processed}/{len(bugs)} threads"
                )
        reaction_counts.sort(key=lambda x: x[0], reverse=True)
        report_embed = discord.Embed(
            title="Bug Report Stats",
            timestamp=datetime.datetime.now(tz=ZoneInfo("Asia/Kolkata")),
        )
        printable_condition_parts = [
            "filtered by [",
            f"{'title: ' + condition + ' AND ' if len(condition) else ''}",
            f"(reaction >= {min_reaction_count}",
            "OR",
            f"messages >= {min_message_count}) ]",
        ]
        stats = [
            f"> {thread.mention} : **{count}** ⬆️, **{thread.message_count}** msgs"
            for count, thread in reaction_counts
        ]
        safe_report, stats = make_report_safe_for_embed(stats)
        if len(stats):
            # todo: consume stats if any not added to safe_report
            pass

        report_embed.description = safe_report
        report_embed.set_footer(text=" ".join(printable_condition_parts))
        await bug_report_msg.edit(content='', embeds=[report_embed])


def make_report_safe_for_embed(report_parts: list[str]) -> tuple[str, list[str]]:
    """Cuts of the list of thread at 4096 characters."""
    final_report = ""
    from_index = 0
    for index, part in enumerate(report_parts):
        if len(final_report) + len(part) >= 4096:
            from_index = index
            break
        final_report += f"\n{part}"
    return final_report, report_parts[from_index:]


def title_passes_condition(title: str, condition_string: str):
    """Check if a title passes a condition"""

    # split title and condition string into parts
    title_parts = title.lower().split()
    condition_parts = condition_string.lower().split(",")

    exclusion_conditions, inclusion_conditions = [], []

    # split conditions into exclusion and inclusion
    for condition in condition_parts:
        if "-" in condition:
            exclusion_conditions.append(condition.split("-", maxsplit=1)[1])
        else:
            inclusion_conditions.append(condition)

    # check if title contains any exclusion conditions
    if any(condition in title_parts for condition in exclusion_conditions):
        return False

    # check if title contains all inclusion conditions
    if any(condition not in title_parts for condition in inclusion_conditions):
        return False

    # if all conditions are met, return True
    return True


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


if __name__ == '__main__':
    print(title_passes_condition("Portal Website bug - Missing restriction options and incorrect options", "-ai"))
