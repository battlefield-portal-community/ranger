"""Scheduled-event helpers for the playtest cog.

Parse the optional playtest time pasted into the modal, and create, reschedule
or cancel the guild voice event that mirrors it. Every Discord call here is
best-effort: a missing permission, a manually deleted event or a wrong-status
transition is logged and reported as ``None`` rather than raised, so the
playtest flow itself never fails because of the event.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone

import discord

from ... import db
from ...config import env
from .announcements import MAX_EPOCH_DIGITS

log = logging.getLogger(__name__)

# A Discord timestamp as copied from discordtimestamps.com: <t:EPOCH> with an
# optional single-letter style suffix (F, R, d, ...).
TIMESTAMP_RE = re.compile(rf"^<t:(\d{{1,{MAX_EPOCH_DIGITS}}})(?::[a-zA-Z])?>$")
BARE_EPOCH_RE = re.compile(rf"^\d{{1,{MAX_EPOCH_DIGITS}}}$")

PARSE_ERROR = (
    "Couldn't parse the playtest time. Paste a Discord timestamp like "
    "<t:1785688200:F> from discordtimestamps.com."
)

# Anything further out than this is far more likely a typo than a real playtest.
MAX_FUTURE_SECONDS = 2 * 365 * 24 * 60 * 60


def parse_playtest_time(raw: str) -> int | None:
    """Parse the modal's time field into epoch seconds, or None when left blank.

    Raises ``ValueError`` with a user-facing message for anything unparseable,
    in the past, or absurdly far in the future.
    """
    value = raw.strip()
    if not value:
        return None

    match = TIMESTAMP_RE.match(value)
    if match:
        epoch = int(match.group(1))
    elif BARE_EPOCH_RE.match(value):
        epoch = int(value)
    else:
        raise ValueError(PARSE_ERROR)

    now = int(time.time())
    if epoch <= now:
        raise ValueError("That playtest time is in the past. Pick a future time.")
    if epoch - now > MAX_FUTURE_SECONDS:
        raise ValueError("That playtest time is more than 2 years away.")
    return epoch


def event_url(guild_id: int, event_id: str) -> str:
    """Public link to a guild scheduled event."""
    return f"https://discord.com/events/{guild_id}/{event_id}"


async def get_event_voice_channel(
    guild: discord.Guild | None,
) -> discord.VoiceChannel | None:
    """Return the voice channel that hosts playtest events, or None if unusable."""
    if not guild:
        return None

    channel_id = env.PLAYTEST_COG_SETTINGS.EVENT_VOICE_CHANNEL_ID
    if not channel_id:
        log.info("EVENT_VOICE_CHANNEL_ID is unset; playtest events are disabled")
        return None

    try:
        channel = guild.get_channel(channel_id) or await guild.fetch_channel(channel_id)
        assert isinstance(channel, discord.VoiceChannel)
        return channel
    except AssertionError:
        log.exception("Playtest event channel is not a VoiceChannel")
    except discord.HTTPException:
        log.exception("Couldn't fetch the playtest event channel")

    return None


async def create_playtest_event(
    guild: discord.Guild | None,
    *,
    name: str,
    start_at: int,
    description: str,
) -> discord.ScheduledEvent | None:
    """Create the voice scheduled event for a playtest, or None if that fails."""
    channel = await get_event_voice_channel(guild)
    if guild is None or channel is None:
        return None

    try:
        return await guild.create_scheduled_event(
            name=name[:100],
            start_time=datetime.fromtimestamp(start_at, tz=timezone.utc),
            entity_type=discord.EntityType.voice,
            channel=channel,
            privacy_level=discord.PrivacyLevel.guild_only,
            description=description[:1000],
        )
    except discord.Forbidden:
        log.warning("Missing Manage Events permission; skipping playtest event")
    except discord.HTTPException:
        log.exception("Failed to create the playtest event")

    return None


async def fetch_event(
    guild: discord.Guild | None, event_id: str
) -> discord.ScheduledEvent | None:
    """Resolve a stored event id, or None if the event no longer exists."""
    if guild is None:
        return None
    try:
        return guild.get_scheduled_event(int(event_id)) or (
            await guild.fetch_scheduled_event(int(event_id))
        )
    except (discord.NotFound, ValueError):
        return None
    except discord.HTTPException:
        log.exception("Failed to fetch playtest event %s", event_id)
        return None


async def cancel_event(event: discord.ScheduledEvent) -> None:
    """Cancel a pending event, or end it if it is already running."""
    try:
        if event.status is discord.EventStatus.scheduled:
            await event.cancel()
        elif event.status is discord.EventStatus.active:
            await event.end()
    except discord.NotFound:
        pass
    except discord.Forbidden:
        log.warning("Missing Manage Events permission to stop event %s", event.id)
    except discord.HTTPException:
        log.exception("Failed to stop playtest event %s", event.id)


async def post_event_link(
    thread: discord.abc.Messageable | None, guild_id: int, event_id: int
) -> None:
    """Post the subscribe link for a freshly created event in the playtest thread."""
    if thread is None:
        return
    try:
        await thread.send(
            f"📅 Voice event created — subscribe here: "
            f"{event_url(guild_id, str(event_id))}"
        )
    except discord.HTTPException:
        log.exception("Failed to post the event link for %s", event_id)


async def sync_playtest_event(
    guild: discord.Guild | None,
    thread: discord.abc.Messageable | None,
    playtest: db.Playtest,
    *,
    new_scheduled_at: int | None,
    name: str,
    description: str,
) -> tuple[str | None, int | None]:
    """Reconcile a playtest's event with its newly submitted time.

    Returns the ``(event_id, ends_at)`` pair the caller should persist; ``(None,
    None)`` means "no live event", whether because none was wanted or because
    every attempt to create or reschedule one failed.
    """
    default_duration = env.PLAYTEST_COG_SETTINGS.EVENT_DEFAULT_DURATION_MINUTES * 60
    old_scheduled_at = playtest.scheduled_at
    # A record can carry a time but no event when the original creation failed.
    old_event_id = playtest.event_id

    async def create_fresh() -> tuple[str | None, int | None]:
        event = await create_playtest_event(
            guild, name=name, start_at=new_scheduled_at, description=description
        )
        if event is None:
            return None, None
        await post_event_link(thread, event.guild_id, event.id)
        return str(event.id), new_scheduled_at + default_duration

    if old_event_id is None:
        return (None, None) if new_scheduled_at is None else await create_fresh()

    if new_scheduled_at is None:
        event = await fetch_event(guild, old_event_id)
        if event is not None:
            await cancel_event(event)
        return None, None

    if new_scheduled_at == old_scheduled_at:
        return old_event_id, playtest.ends_at

    event = await fetch_event(guild, old_event_id)
    if event is None or event.status in (
        discord.EventStatus.completed,
        discord.EventStatus.cancelled,
    ):
        return await create_fresh()

    if event.status is discord.EventStatus.active:
        await cancel_event(event)
        return await create_fresh()

    try:
        await event.edit(
            start_time=datetime.fromtimestamp(new_scheduled_at, tz=timezone.utc)
        )
    # Keep tracking the event when the move fails: its card keeps the stale start
    # time, but the scheduler keys off the row's scheduled_at and still starts and
    # ends it at the new one — better than orphaning a live event and creating a
    # duplicate on the next update.
    except discord.Forbidden:
        log.warning("Missing Manage Events permission to move event %s", event.id)
        return old_event_id, playtest.ends_at
    except discord.HTTPException:
        log.exception("Failed to reschedule playtest event %s", event.id)
        return old_event_id, playtest.ends_at

    return str(event.id), new_scheduled_at + default_duration
