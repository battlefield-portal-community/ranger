"""Playtest scheduling.

Users open a modal (from a persistent "Schedule Playtest" button or the
``/schedule-playtest`` command), fill in a description, an optional experience
code and the regions to ping, and the bot posts an announcement that pings the
selected region roles and opens a thread on it. Each user's region selection is
remembered and pre-filled next time. An existing playtest can be edited from its
thread via ``/update-playtest-message``.

The package is laid out as:

- :mod:`.cog` — the :class:`PlaytestCog`, slash commands and menu message.
- :mod:`.announcements` — helpers that build/post/edit the announcement message.
- :mod:`.ui` — the modals and the persistent menu view.
"""

from .cog import PlaytestCog, setup

__all__ = ["PlaytestCog", "setup"]
