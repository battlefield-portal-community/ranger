"""The feedback forms: field limits and the starter-message body.

A forum post's starter message is capped at 2000 characters, while a modal field
allows 4000, so the modal's ``max_length`` values are derived here rather than
guessed: the fixed part of the body is measured and the rest is split across the
fields. Nothing is truncated, and :func:`build_body` refuses to build a body that
would not fit — which is a configuration bug (a longer ``DEFAULT_GAME_TAG``), never
something a reporter typed.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...config import FeedbackCogSettings, env

DISCORD_MESSAGE_LIMIT = 2000
THREAD_NAME_LIMIT = 100

# A Discord snowflake is a 64-bit int, so the reporter mention is at most 19 digits.
MAX_SNOWFLAKE_DIGITS = 19

# What the body says instead of asking, because BF6 is the default game.
_GAME_NOTE = "(assumed)"

# Word joining the reporter mention to the headline. The same for both kinds, so
# the fixed overhead stays identical and the field budgets below stay predictable.
_REPORTER_VERB = "reported by"


@dataclass(frozen=True)
class FormField:
    """One modal input, and (optionally) one section of the filed body."""

    key: str
    label: str
    hint: str
    limit: int
    paragraph: bool = True
    # The summary names the thread instead of appearing in the body.
    in_body: bool = True


FORMS: dict[str, tuple[FormField, ...]] = {
    "bug": (
        FormField(
            key="summary",
            label="Summary",
            hint="One sentence: it becomes the thread title.",
            limit=100,
            paragraph=False,
            in_body=False,
        ),
        FormField(
            key="what_happens",
            label="What happens",
            hint="The bug itself. A clip link works if it is easier to show.",
            limit=900,
        ),
        FormField(
            key="steps",
            label="Steps to reproduce",
            hint="How a moderator can trigger it.",
            limit=700,
        ),
    ),
    "feature": (
        FormField(
            key="summary",
            label="Summary",
            hint="One sentence: it becomes the thread title.",
            limit=100,
            paragraph=False,
            in_body=False,
        ),
        FormField(
            key="want",
            label="What you want",
            hint="The change you are asking for.",
            limit=800,
        ),
        FormField(
            key="why",
            label="Why it helps",
            hint="What it would improve for you or for everyone.",
            limit=450,
        ),
        FormField(
            key="example",
            label="Example",
            hint="A game, a mode or a link that shows the idea.",
            limit=450,
        ),
    ),
}


def fields(kind: str) -> tuple[FormField, ...]:
    """The inputs of one form, in display order."""
    return FORMS[kind]


def field_limits(kind: str) -> dict[str, int]:
    """Modal ``max_length`` per input key."""
    return {field.key: field.limit for field in fields(kind)}


def _settings() -> FeedbackCogSettings | None:
    return env.FEEDBACK_COG_SETTINGS


def default_game() -> str:
    """The game tag stamped on every post, used while settings are absent too."""
    settings = _settings()
    return "BF6" if settings is None else settings.DEFAULT_GAME_TAG


def _render(
    kind: str, game: str, reporter_id: int | str, values: dict[str, str]
) -> str:
    lines = [f"{game} {_GAME_NOTE} · {_REPORTER_VERB} <@{reporter_id}>"]
    for field in fields(kind):
        if not field.in_body:
            continue
        lines.extend(["", f"**{field.label}:**", values[field.key]])
    return "\n".join(lines)


def body_overhead(kind: str) -> int:
    """Length of the body with every free-text field empty."""
    values = {field.key: "" for field in fields(kind)}
    return len(_render(kind, default_game(), "0" * MAX_SNOWFLAKE_DIGITS, values))


def body_budget(kind: str) -> int:
    """How much of the message the free-text fields may use."""
    return DISCORD_MESSAGE_LIMIT - body_overhead(kind)


def max_body_length(kind: str) -> int:
    """Worst-case body length when every input is at its cap."""
    return body_overhead(kind) + sum(
        field.limit for field in fields(kind) if field.in_body
    )


def limits_fit(kind: str) -> bool:
    """Whether this form's caps still fit the message limit."""
    return max_body_length(kind) <= DISCORD_MESSAGE_LIMIT


def build_body(kind: str, reporter_id: int | str, values: dict[str, str]) -> str:
    """Assemble the starter message for a filed post."""
    body = _render(kind, default_game(), reporter_id, values)
    if len(body) > DISCORD_MESSAGE_LIMIT:
        raise ValueError(
            f"{kind} body is {len(body)} chars, over Discord's {DISCORD_MESSAGE_LIMIT}"
        )
    return body


def thread_name(summary: str) -> str:
    """The thread title derived from the summary: one line, capped at 100 chars."""
    return " ".join(summary.split())[:THREAD_NAME_LIMIT]
