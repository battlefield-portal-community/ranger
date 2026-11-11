"""Provision a scratch Discord server for the feedback intake cog.

Creates — or tops up, so re-running is safe — the category, the bug and feature
forums with the tags the cog resolves by name, and the intake channel with
``@everyone`` muted. It then prints the three ``FEEDBACK_COG_SETTINGS__*`` ids, or
starts the bot with them::

    python -m app.setup_feedback_test --guild-id <test server id> --run

The bot needs Administrator in the test server: it has to create channels, edit
forum tags and post the intake message. Nothing here deletes anything.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

import discord

from .config import FeedbackCogSettings, env

log = logging.getLogger(__name__)

REASON = "Feedback intake test setup"

CATEGORY_NAME = "🛠 Portal Feedback | Ripple"
INTAKE_CHANNEL_NAME = "📮・submit-feedback"
BUG_FORUM_NAME = "bug-reports"
FEATURE_FORUM_NAME = "feature-requests"

# The names the cog resolves, plus the status tags the live forums lack (Working,
# Declined) so the whole alias table can be exercised on the test server.
BUG_TAGS = (
    "BF6",
    "BF2042",
    "Editor",
    "Scripts",
    "Godot",
    "Rules editor",
    "Noted",
    "Working",
    "Patched",
    "Needs Info",
    "Duplicate",
    "Declined",
)
FEATURE_TAGS = (
    "BF6",
    "BF2042",
    "feature-request",
    "game-ui",
    "logic-editor",
    "godot",
    "Noted",
    "Working",
    "Added",
    "Needs Info",
    "Duplicate",
    "Declined",
)

# Settings field -> env var, in the order they are printed.
ENV_KEYS = (
    ("MENU_CHANNEL_ID", "FEEDBACK_COG_SETTINGS__MENU_CHANNEL_ID"),
    ("BUG_FORUM_ID", "FEEDBACK_COG_SETTINGS__BUG_FORUM_ID"),
    ("FEATURE_FORUM_ID", "FEEDBACK_COG_SETTINGS__FEATURE_FORUM_ID"),
)


def _find(channels: list, name: str, kind: discord.ChannelType):
    for channel in channels:
        if channel.name == name and channel.type is kind:
            return channel
    return None


async def ensure_category(guild: discord.Guild, channels: list):
    category = _find(channels, CATEGORY_NAME, discord.ChannelType.category)
    if category is not None:
        print(f"= category {CATEGORY_NAME!r} already exists")
        return category
    category = await guild.create_category(CATEGORY_NAME, reason=REASON)
    print(f"+ created category {CATEGORY_NAME!r}")
    return category


async def ensure_forum(
    guild, channels: list, name: str, tag_names: tuple[str, ...], category
):
    forum = _find(channels, name, discord.ChannelType.forum)
    if forum is None:
        forum = await guild.create_forum(
            name,
            category=category,
            topic="Filed by Ranger from the intake form.",
            available_tags=[discord.ForumTag(name=tag) for tag in tag_names],
            reason=REASON,
        )
        print(f"+ created forum #{name} with {len(tag_names)} tags")
        return forum

    present = {tag.name.casefold() for tag in forum.available_tags}
    missing = [tag for tag in tag_names if tag.casefold() not in present]
    if missing:
        await forum.edit(
            available_tags=[
                *forum.available_tags,
                *(discord.ForumTag(name=tag) for tag in missing),
            ],
            reason=REASON,
        )
        print(f"+ added tags to #{name}: {', '.join(missing)}")
    else:
        print(f"= forum #{name} already has every tag")
    return forum


async def ensure_intake(guild, channels: list, category):
    channel = _find(channels, INTAKE_CHANNEL_NAME, discord.ChannelType.text)
    if channel is not None:
        print(f"= channel {INTAKE_CHANNEL_NAME!r} already exists")
        return channel
    channel = await guild.create_text_channel(
        INTAKE_CHANNEL_NAME,
        category=category,
        topic=(
            "Press a button and fill in the form; Ranger files the post in the "
            "right forum and replies with a link."
        ),
        # Only the intake message lives here; the bot is admin, so it still posts.
        overwrites={
            discord.Object(id=guild.id): discord.PermissionOverwrite(
                send_messages=False
            )
        },
        reason=REASON,
    )
    print(f"+ created channel {INTAKE_CHANNEL_NAME!r} with @everyone muted")
    return channel


async def require_tag_on(forum) -> None:
    """Match the live bug forum, where a post without a tag is rejected."""
    if forum.flags.require_tag:
        print(f"= #{forum.name} already requires a tag")
        return
    await forum.edit(require_tag=True, reason=REASON)
    print(f"= #{forum.name} now requires a tag")


async def provision(guild_id: int) -> dict[str, int]:
    """Create everything the cog needs, returning the three channel ids."""
    client = discord.Client(intents=discord.Intents.none())
    await client.login(env.BOT_SETTINGS.DISCORD_TOKEN.get_secret_value())
    try:
        guild = await client.fetch_guild(guild_id)
        print(f"Provisioning {guild.name!r} (id {guild.id})")
        channels = list(await guild.fetch_channels())
        category = await ensure_category(guild, channels)

        bug_forum = await ensure_forum(
            guild, channels, BUG_FORUM_NAME, BUG_TAGS, category
        )
        await require_tag_on(bug_forum)
        feature_forum = await ensure_forum(
            guild, channels, FEATURE_FORUM_NAME, FEATURE_TAGS, category
        )
        intake = await ensure_intake(guild, channels, category)
        return {
            "MENU_CHANNEL_ID": intake.id,
            "BUG_FORUM_ID": bug_forum.id,
            "FEATURE_FORUM_ID": feature_forum.id,
        }
    finally:
        await client.close()


def write_env_file(path: Path, values: dict[str, int]) -> None:
    """Write the three ids into an env file, leaving every other line alone."""
    lines = path.read_text().splitlines() if path.exists() else []
    pending = {key: str(values[field]) for field, key in ENV_KEYS}
    kept: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in pending:
            kept.append(f"{key}={pending.pop(key)}")
        else:
            kept.append(line)
    kept.extend(f"{key}={value}" for key, value in pending.items())
    path.write_text("\n".join(kept) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision a test server for the feedback intake cog."
    )
    parser.add_argument(
        "--guild-id", type=int, required=True, help="the test server's id"
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="also write the three ids into this env file",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="start the bot with these ids after provisioning",
    )
    args = parser.parse_args()

    logging.basicConfig(level=env.BOT_SETTINGS.LOG_LEVEL)
    if env.BOT_SETTINGS.GUILD_ID != args.guild_id:
        print(
            f"! BOT_SETTINGS__GUILD_ID is {env.BOT_SETTINGS.GUILD_ID}, not "
            f"{args.guild_id}: point it at the test server or the commands and the "
            "intake message will belong to the wrong guild."
        )

    values = asyncio.run(provision(args.guild_id))

    print("\nEnvironment for the bot:")
    for field, key in ENV_KEYS:
        print(f"  {key}={values[field]}")
    if args.env_file:
        write_env_file(args.env_file, values)
        print(f"\nWrote those keys to {args.env_file}")

    if not args.run:
        print("\nRestart the bot with those values to see the intake message appear.")
        return

    # Local-testing shortcut: same bot as `app`, with the ids injected instead of
    # requiring a rewritten env file.
    env.FEEDBACK_COG_SETTINGS = FeedbackCogSettings(
        MENU_CHANNEL_ID=values["MENU_CHANNEL_ID"],
        BUG_FORUM_ID=values["BUG_FORUM_ID"],
        FEATURE_FORUM_ID=values["FEATURE_FORUM_ID"],
    )
    from .__main__ import start

    print("\nStarting the bot. Ctrl-C to stop it.")
    start()


if __name__ == "__main__":
    main()
