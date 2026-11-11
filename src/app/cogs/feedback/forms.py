"""The feedback forms: field limits and the starter-message body.

A forum post's starter message is capped at 2000 characters, while a modal field
allows 4000, so the modal's ``max_length`` values are derived here rather than
guessed: the fixed part of the body is measured and the rest is split across the
fields. Nothing is truncated, and :func:`build_body` refuses to build a body that
would not fit — which is a configuration bug (the limits in :data:`FORMS`), never
something a reporter typed.
"""

from __future__ import annotations

from dataclasses import dataclass

DISCORD_MESSAGE_LIMIT = 2000
THREAD_NAME_LIMIT = 100

# A Discord snowflake is a 64-bit int, so the reporter mention is at most 19 digits.
MAX_SNOWFLAKE_DIGITS = 19

# Discord prints the posting application's name inline with the first line of a
# message, so a body starting on the first line is glued to "Ranger". A leading
# empty line pushes it down; Discord trims whitespace, so the blank line is a
# zero-width space, which it does not trim.
_LEADING_BLANK = "\u200b\n"

# Discord's subtext markdown, so the reporter credit reads as a footnote under the
# report instead of competing with it.
_SUBTEXT = "-# "

# The credit line closing every body. The same for both kinds, so the fixed overhead
# stays identical and the field budgets below stay predictable.
_REPORTER_VERB = "Reported by"


@dataclass(frozen=True)
class FormField:
    """One modal input, and (optionally) one section of the filed body."""

    key: str
    label: str
    limit: int
    # Shown under the label in the modal; empty means no description at all.
    hint: str = ""
    paragraph: bool = True
    # Fields left empty are left out of the body, so an optional one costs nothing.
    required: bool = True
    # The title names the thread instead of appearing in the body.
    in_body: bool = True


FORMS: dict[str, tuple[FormField, ...]] = {
    "bug": (
        FormField(
            key="summary",
            label="Title",
            limit=100,
            paragraph=False,
            in_body=False,
        ),
        FormField(
            key="what_happened",
            label="What happened",
            hint="The bug itself. Markdown works; a clip link is fine too.",
            limit=900,
        ),
        FormField(
            key="steps",
            label="Steps to reproduce",
            hint="How a moderator can trigger it. Markdown works.",
            limit=700,
        ),
    ),
    "feature": (
        FormField(
            key="summary",
            label="Title",
            limit=100,
            paragraph=False,
            in_body=False,
        ),
        FormField(
            key="want",
            label="Your request",
            hint="The change you are asking for. Markdown works.",
            limit=800,
        ),
        FormField(
            key="why",
            label="How it helps",
            # One field rather than two: a modal has five slots, and the tag picker
            # and the upload take two of the feature form's.
            hint=(
                "What it would improve, and an example if you have one "
                "(a game, a mode, a link). Markdown works."
            ),
            limit=900,
        ),
    ),
}


def fields(kind: str) -> tuple[FormField, ...]:
    """The inputs of one form, in display order."""
    return FORMS[kind]


def field_limits(kind: str) -> dict[str, int]:
    """Modal ``max_length`` per input key."""
    return {field.key: field.limit for field in fields(kind)}


def _render(kind: str, reporter_id: int | str, values: dict[str, str]) -> str:
    # The game is only in the applied tags now, so it is not repeated in the body.
    sections = [
        f"**{field.label}:**\n{values[field.key]}"
        for field in fields(kind)
        if field.in_body and values[field.key].strip()
    ]
    sections.append(f"{_SUBTEXT}{_REPORTER_VERB} <@{reporter_id}>")
    return _LEADING_BLANK + "\n\n".join(sections)


def body_overhead(kind: str) -> int:
    """The body's fixed cost: the credit line and every heading, text aside.

    Measured by rendering each section with a one-character stand-in for its text
    and discounting the stand-ins, since an empty section is left out entirely.
    """
    values = {field.key: "x" for field in fields(kind)}
    return len(_render(kind, "0" * MAX_SNOWFLAKE_DIGITS, values)) - sum(
        1 for field in fields(kind) if field.in_body
    )


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
    body = _render(kind, reporter_id, values)
    if len(body) > DISCORD_MESSAGE_LIMIT:
        raise ValueError(
            f"{kind} body is {len(body)} chars, over Discord's {DISCORD_MESSAGE_LIMIT}"
        )
    return body


def thread_name(summary: str) -> str:
    """The thread title derived from the summary: one line, capped at 100 chars."""
    return " ".join(summary.split())[:THREAD_NAME_LIMIT]
