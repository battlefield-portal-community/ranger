"""Dedupe for the feedback intake.

The preflight runs before a post is filed: the summary and body are reduced to
plain tokens and searched with FTS5, then the hits are ranked by title-token
overlap so a reworded report still matches. Raw reporter text must never reach
``MATCH`` — a quote, a hyphen or a bare ``AND`` is FTS5 syntax and raises.

The FTS query ORs the quoted tokens instead of ANDing them: an AND drops every
reworded report that changes one word, and the title overlap below is what decides
a duplicate anyway. FTS only has to propose candidates that bm25 ranks.

:data:`PENDING` keeps a submit that stopped at the duplicate prompt, so "File
anyway" can finish it. It is in memory on purpose: after a restart the click is
gone and the reporter submits again.
"""

from __future__ import annotations

import re
import time

from ... import db

# Title-token overlap at or above this counts as the same report.
TITLE_SIMILARITY = 0.4

# FTS hits examined before ranking, and threads offered in the prompt.
CANDIDATES = 20
SUGGESTIONS = 3

# How long a "File anyway" click stays valid, in seconds.
PENDING_TTL = 600

# user id -> (expiry, submission). The payload type lives in ``ui.modals``.
PENDING: dict[int, tuple[float, object]] = {}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    """Split text into the lowercase alphanumeric tokens FTS5 can be quoted with."""
    return _TOKEN_RE.findall(text.lower())


def normalise(text: str) -> str:
    """A comparable form of free text: lowercase tokens joined by single spaces."""
    return " ".join(tokens(text))


def _match_query(text: str) -> str:
    quoted = (f'"{token}"' for token in sorted(set(tokens(text))))
    return " OR ".join(quoted)


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


async def search(summary: str, body: str) -> list[db.FeedbackPost]:
    """Return up to :data:`SUGGESTIONS` filed posts that look like this report."""
    query = _match_query(f"{summary} {body}")
    if not query:
        return []
    wanted = set(tokens(summary))
    matches = [
        (overlap, hit)
        for hit in await db.search_feedback(query, limit=CANDIDATES)
        if (overlap := _jaccard(wanted, set(tokens(hit.summary)))) >= TITLE_SIMILARITY
    ]
    matches.sort(key=lambda match: match[0], reverse=True)
    return [hit for _, hit in matches[:SUGGESTIONS]]


def remember(user_id: int, submission: object) -> None:
    """Hold a submit that stopped at the duplicate prompt."""
    now = time.monotonic()
    for key, (expiry, _) in list(PENDING.items()):
        if expiry <= now:
            del PENDING[key]
    PENDING[user_id] = (now + PENDING_TTL, submission)


def take(user_id: int) -> object | None:
    """Pop a held submit, or None when there is none or it has expired."""
    entry = PENDING.pop(user_id, None)
    if entry is None:
        return None
    expiry, submission = entry
    return None if expiry <= time.monotonic() else submission
