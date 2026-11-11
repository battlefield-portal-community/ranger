"""Provision a scratch Discord server for the feedback intake cog.

Creates — or tops up, so re-running is safe — the category, the bug and feature
forums with the tags the cog resolves by name, and the intake channel with
``@everyone`` muted. It then prints the three ``FEEDBACK_COG_SETTINGS__*`` ids, or
starts the bot with them::

    python -m app.setup_feedback_test --guild-id <test server id> --run

``--dry-run`` reports what would be created, tagged or edited and writes nothing,
which is the way to look before touching a server that already has content::

    python -m app.setup_feedback_test --guild-id <test server id> --dry-run

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
from .tls import use_certifi

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


async def ensure_category(guild: discord.Guild, channels: list, dry_run: bool):
    category = _find(channels, CATEGORY_NAME, discord.ChannelType.category)
    if category is not None:
        print(f"= category {CATEGORY_NAME!r} already exists")
        return category
    if dry_run:
        print(f"+ would create category {CATEGORY_NAME!r}")
        return None
    category = await guild.create_category(CATEGORY_NAME, reason=REASON)
    print(f"+ created category {CATEGORY_NAME!r}")
    return category


async def ensure_forum(
    guild,
    channels: list,
    name: str,
    tag_names: tuple[str, ...],
    category,
    dry_run: bool,
):
    forum = _find(channels, name, discord.ChannelType.forum)
    if forum is None:
        if dry_run:
            print(f"+ would create forum #{name} with {len(tag_names)} tags")
            return None
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
        if dry_run:
            print(f"+ would add tags to #{name}: {', '.join(missing)}")
            return forum
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


async def ensure_intake(guild, channels: list, category, dry_run: bool):
    channel = _find(channels, INTAKE_CHANNEL_NAME, discord.ChannelType.text)
    if channel is not None:
        print(f"= channel {INTAKE_CHANNEL_NAME!r} already exists")
        return channel
    if dry_run:
        print(f"+ would create channel {INTAKE_CHANNEL_NAME!r} with @everyone muted")
        return None
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


async def require_tag_on(forum, dry_run: bool) -> None:
    """Match the live bug forum, where a post without a tag is rejected."""
    if forum is None:
        # A dry run on a server that has no bug forum yet: the new forum is
        # created with the flag, so there is nothing to report.
        return
    if forum.flags.require_tag:
        print(f"= #{forum.name} already requires a tag")
        return
    if dry_run:
        print(f"+ would make #{forum.name} require a tag")
        return
    await forum.edit(require_tag=True, reason=REASON)
    print(f"= #{forum.name} now requires a tag")


async def provision(guild_id: int, dry_run: bool) -> dict[str, int | None]:
    """Create everything the cog needs, returning the three channel ids.

    A dry run returns None for anything that does not exist yet, because nothing
    gets an id without being created.
    """
    client = discord.Client(intents=discord.Intents.default())
    try:
        # Inside the try: a failed login has already opened the HTTP session.
        await client.login(env.BOT_SETTINGS.DISCORD_TOKEN.get_secret_value())
        guild = await client.fetch_guild(guild_id)
        suffix = " — dry run, nothing will be changed" if dry_run else ""
        print(f"Provisioning {guild.name!r} (id {guild.id}){suffix}")
        channels = list(await guild.fetch_channels())
        category = await ensure_category(guild, channels, dry_run)

        bug_forum = await ensure_forum(
            guild, channels, BUG_FORUM_NAME, BUG_TAGS, category, dry_run
        )
        await require_tag_on(bug_forum, dry_run)
        feature_forum = await ensure_forum(
            guild, channels, FEATURE_FORUM_NAME, FEATURE_TAGS, category, dry_run
        )
        intake = await ensure_intake(guild, channels, category, dry_run)
        return {
            "MENU_CHANNEL_ID": None if intake is None else intake.id,
            "BUG_FORUM_ID": None if bug_forum is None else bug_forum.id,
            "FEATURE_FORUM_ID": None if feature_forum is None else feature_forum.id,
        }
    finally:
        await close_client(client)


async def close_client(client: discord.Client) -> None:
    """Close the throwaway client, including the connector discord.py keeps."""
    await client.close()
    # discord.py hands its own connector to the session, and closing the session
    # does not close it; aiohttp warns about that on shutdown if it is left open.
    connector = getattr(client.http, "connector", None)
    if connector is not None and not connector.closed:
        await connector.close()


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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change, without creating or editing anything",
    )
    args = parser.parse_args()

    if args.dry_run and args.run:
        parser.error("--dry-run cannot also start the bot with --run")
    if args.dry_run and args.env_file:
        parser.error("--dry-run writes nothing, so it cannot --env-file")

    logging.basicConfig(level=env.BOT_SETTINGS.LOG_LEVEL)
    bundle = use_certifi()
    if bundle:
        print(f"= TLS: trusting certifi's CA bundle ({bundle})")
    if not env.BOT_SETTINGS.DISCORD_TOKEN.get_secret_value():
        raise SystemExit(
            "BOT_SETTINGS__DISCORD_TOKEN is empty: set it in the environment "
            "(or .env) before provisioning."
        )
    if env.BOT_SETTINGS.GUILD_ID != args.guild_id:
        print(
            f"! BOT_SETTINGS__GUILD_ID is {env.BOT_SETTINGS.GUILD_ID}, not "
            f"{args.guild_id}: point it at the test server or the commands and the "
            "intake message will belong to the wrong guild."
        )

    try:
        values = asyncio.run(provision(args.guild_id, args.dry_run))
    except discord.LoginFailure:
        raise SystemExit(
            "Discord rejected the bot token (BOT_SETTINGS__DISCORD_TOKEN)."
        )
    except discord.Forbidden:
        raise SystemExit(
            "The bot is not allowed to do that: it needs Administrator (or at "
            "least Manage Channels) in the test server."
        )
    except discord.NotFound:
        raise SystemExit(
            f"Guild {args.guild_id} was not found, or the bot is not a member of it."
        )
    except discord.HTTPException as exc:
        raise SystemExit(f"Discord returned an error: {exc}")
    except OSError as exc:
        raise SystemExit(f"Could not reach Discord: {exc}")

    if args.dry_run:
        print("\nIds this run would produce:")
    else:
        print("\nEnvironment for the bot:")
    for field, key in ENV_KEYS:
        value = values[field]
        print(f"  {key}={'(would be created)' if value is None else value}")
    if args.dry_run:
        print("\nDry run: nothing was created, edited or written.")
        return
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
