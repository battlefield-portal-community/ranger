"""Access to the feedback cog settings.

The settings block is optional at import time (an image can ship before the
deployment env names a menu channel), so the cog checks for it once and everything
else that needs a value goes through here instead of asserting on ``env``.
"""

from __future__ import annotations

from ...config import FeedbackCogSettings, env


def configured() -> FeedbackCogSettings | None:
    """The settings block, or None while the cog is not configured."""
    return env.FEEDBACK_COG_SETTINGS


def settings() -> FeedbackCogSettings:
    """The settings block, for callers that only run once the cog is active."""
    current = configured()
    if current is None:
        raise RuntimeError("the feedback cog settings are not configured")
    return current
