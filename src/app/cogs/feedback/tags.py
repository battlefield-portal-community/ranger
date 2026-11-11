"""Forum tag mapping for the feedback intake cog.

The bug and feature forums do not share a tag vocabulary, so nothing here assumes
one: every name is resolved against the forum's own ``available_tags`` and matched
case-insensitively. A status is only ever what a thread's tags actually say, which
is why :func:`status_from_tags` falls back to ``open`` instead of inventing one.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

import discord

from . import settings as feedback_settings

log = logging.getLogger(__name__)

OPEN = "open"

# Status -> the tag names that mean it. ``working`` and ``declined`` have no tag in
# the live forums today; they stay in the vocabulary so creating those tags later is
# enough to make them live.
STATUS_ALIASES: dict[str, frozenset[str]] = {
    "noted": frozenset({"noted"}),
    "patched": frozenset({"patched", "fixed", "resolved"}),
    "added": frozenset({"added", "shipped", "implemented"}),
    "needs-info": frozenset({"needs info", "needs-info", "more info"}),
    "duplicate": frozenset({"duplicate", "dupe"}),
    "working": frozenset({"working", "in progress"}),
    "declined": frozenset({"declined", "wontfix", "won't do"}),
}

# The statuses each kind of post can reach. A bug is patched and a feature is added;
# expecting an "Added" tag in the bug forum, or "Patched" in the feature forum, only
# ever reports a hole that nobody would fill. The topic tag (``feature-request``) is
# not a status: it is applied once, when the post is filed.
STATUSES_BY_KIND: dict[str, tuple[str, ...]] = {
    "bug": ("noted", "working", "patched", "needs-info", "duplicate", "declined"),
    "feature": ("noted", "working", "added", "needs-info", "duplicate", "declined"),
}

# When a thread carries several status tags, the first match here wins: a closed
# thread that is also still marked noted is closed.
_PRIORITY = (
    "patched",
    "added",
    "declined",
    "duplicate",
    "needs-info",
    "working",
    "noted",
)

# Tags warned about once per process: every game and topic tag lands here, and a
# retag must not repeat the whole list.
_warned_unknown: set[str] = set()


def normalise(name: str) -> str:
    """Lowercase and collapse whitespace, underscores and hyphens."""
    return re.sub(r"[\s_-]+", " ", name.strip().lower())


_ALIAS_TO_STATUS = {
    normalise(alias): status
    for status, aliases in STATUS_ALIASES.items()
    for alias in aliases
}


def status_from_tags(tags: Iterable[discord.ForumTag | str]) -> str:
    """Derive a status from the tags applied to a thread.

    Accepts :class:`discord.ForumTag` objects or bare names, so the seeded export
    can reuse it.
    """
    found: set[str] = set()
    for tag in tags:
        name = tag if isinstance(tag, str) else tag.name
        status = _ALIAS_TO_STATUS.get(normalise(name))
        if status is None:
            _warn_unknown(name)
            continue
        found.add(status)
    for status in _PRIORITY:
        if status in found:
            return status
    return OPEN


def _warn_unknown(name: str) -> None:
    if name in _warned_unknown:
        return
    _warned_unknown.add(name)
    log.warning("Feedback tag %r is not a known status; it is ignored", name)


def resolve(forum: discord.ForumChannel, name: str) -> discord.ForumTag | None:
    """Return the forum's tag called ``name``, or None when it does not exist."""
    wanted = normalise(name)
    for tag in forum.available_tags:
        if normalise(tag.name) == wanted:
            return tag
    return None


def game_tag(forum: discord.ForumChannel) -> discord.ForumTag | None:
    """The tag every filed post carries (the game it was reported for)."""
    return resolve(forum, feedback_settings.settings().DEFAULT_GAME_TAG)


def feature_tag(forum: discord.ForumChannel) -> discord.ForumTag | None:
    """The tag marking a post as a feature request."""
    return resolve(forum, feedback_settings.settings().FEATURE_TAG)


def tag_report(forum: discord.ForumChannel, kind: str) -> str:
    """Describe a forum's real tags, so a rename shows up in the log.

    Only the statuses that ``kind`` of post can reach are reported missing.
    """
    names = [tag.name for tag in forum.available_tags]
    present = {normalise(name) for name in names}
    missing = sorted(
        status
        for status in STATUSES_BY_KIND[kind]
        if not present & {normalise(alias) for alias in STATUS_ALIASES[status]}
    )
    return (
        f"Feedback tags in {forum.name!r}: {', '.join(names) or '(none)'}"
        f" | no tag for: {', '.join(missing) or '(nothing missing)'}"
    )
