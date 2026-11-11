"""Feedback intake: one audited path into the forums.

A player presses a button in the intake channel, fills a modal and nothing else.
Ranger files the post in the bug or feature forum with the right tags, and mirrors
the thread's own status tag into SQLite so the later cleanup work has history to
query.

The package is laid out as:

- :mod:`.cog` — the cog, the intake menu message and the tag mirror listener.
- :mod:`.tags` — the forum tag vocabulary and the status derivation.
- :mod:`.forms` — the field limits and the starter-message body.
- :mod:`.dedupe` — the FTS5 preflight and the deferred-submit map.
- :mod:`.ui` — the modals, the persistent menu view and the duplicate prompt.
"""

from .cog import FeedbackCog, setup

__all__ = ["FeedbackCog", "setup"]
