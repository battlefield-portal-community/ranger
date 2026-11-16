"""Announcement for the playtest cog.

Build, post and edit the components v2 layout that pings the selected region
roles when a playtest is scheduled or later updated. One container holds the
header, the experience details beside a thumbnail of the map when the code
resolves, the description at full width, and the code/regions/scheduler lines.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

import discord
from discord import TextChannel

from ...config import env
from .experience import Experience

log = logging.getLogger(__name__)

# API caps for a components v2 message: total components, and the total number of
# characters across every text display. Both are counted recursively (containers
# and sections included).
MAX_COMPONENTS = 40
MAX_TEXT_CHARS = 4000

# What the modal lets a scheduler type. Comfortably below MAX_TEXT_CHARS so the
# static parts of the announcement still fit alongside a long description; the view
# trims the description against the real total at render time.
DESCRIPTION_MAX_LENGTH = 3500

# Experience codes are always short (6 chars for a BF Portal code). We enforce
# this on the modal input so the announcement's fixed overhead stays bounded.
EXPERIENCE_CODE_MAX_LENGTH = 6

# A Discord snowflake (user id) is a 64-bit int, so at most 19 digits; round up
# to 20 for a little headroom.
MAX_SNOWFLAKE_DIGITS = 20

# Show at most this many map names inline; the rest collapse into "+N more".
MAX_MAPS_SHOWN = 8

# Emoji and title pools for the announcement header. One of each is picked
# independently but deterministically per playtest (seeded on the announcement
# message id) so the header stays stable across edits.
ANNOUNCEMENT_EMOJIS = (
    "🚀",
    "⚡",
    "🔥",
    "🎉",
    "🕹️",
    "👾",
    "🎯",
    "🛠️",
    "🎮",
    "🧪",
    "🎲",
    "🏁",
    "💥",
    "🎖️",
    "🚁",
)

ANNOUNCEMENT_TITLES = (
    "Playtest Incoming",
    "Fresh Playtest Drop",
    "New Playtest Live",
    "Playtest Time",
    "Jump Into a Playtest",
    "Playtest Needs You",
    "New Playtest - Dive In",
    "Help Us Test This",
    "New Playtest",
    "New Experiment Live",
    "Playtest Just Dropped",
    "New Playtest Ready",
    "New Playtest Deployed",
    "New Mission: Playtest",
    "Playtest Inbound",
)

# The container's accent bar, picked by the same seed as the header.
ANNOUNCEMENT_ACCENTS = (
    discord.Color.blurple(),
    discord.Color.gold(),
    discord.Color.fuchsia(),
    discord.Color.green(),
)


def pick_announcement_header(seed: int) -> str:
    """Deterministically pick an emoji and title so it's stable across edits."""
    emoji = ANNOUNCEMENT_EMOJIS[seed % len(ANNOUNCEMENT_EMOJIS)]
    title = ANNOUNCEMENT_TITLES[
        (seed // len(ANNOUNCEMENT_EMOJIS)) % len(ANNOUNCEMENT_TITLES)
    ]
    return f"{emoji} {title}"


def pick_accent(seed: int) -> discord.Color:
    """Deterministically pick the container accent colour."""
    return ANNOUNCEMENT_ACCENTS[seed % len(ANNOUNCEMENT_ACCENTS)]


def header_text(seed: int) -> str:
    """The heading line of the announcement, suited for a text display."""
    return f"# {pick_announcement_header(seed)}"


# Longest possible "# <emoji> <title>" line. The pools are static, so this is
# computed once at import.
_MAX_HEADER_LINE = max(
    len(header_text(seed))
    for seed in range(len(ANNOUNCEMENT_EMOJIS) * len(ANNOUNCEMENT_TITLES))
)


def maps_line(maps: list[str]) -> str:
    """Comma-joined map list, capped with a "+N more" suffix for long rotations."""
    shown = maps[:MAX_MAPS_SHOWN]
    line = ", ".join(f"`{name}`" for name in shown)
    remaining = len(maps) - len(shown)
    if remaining > 0:
        line += f" … +{remaining} more"
    return line


def experience_block(experience: Experience) -> str:
    """Render the looked-up experience as a markdown block for the announcement."""
    lines = [f"### 🎮 {experience.name}"]
    stats = []
    if experience.players:
        stats.append(f"{experience.players} players")
    if experience.likes:
        stats.append(f"👍 {experience.likes}")
    if experience.updated:
        stats.append(f"<t:{experience.updated}:R>")
    if stats:
        lines.append("-# " + " · ".join(stats))
    if experience.maps:
        lines.append(maps_line(experience.maps))
    if experience.tags:
        lines.append("-# " + ", ".join(experience.tags))
    return "\n".join(lines)


def meta_texts(
    code: str,
    roles: list[discord.Role],
    user_id: int,
    experience: Experience | None,
) -> list[str]:
    """The trailing lines: code/regions, an optional warning, and the footer."""
    details = [f"**Experience Code:** `{code}`"] if code else []
    details.append(f"**Regions:** {' '.join(r.mention for r in roles) or '—'}")

    texts = ["\n".join(details)]
    if code and experience is None:
        texts.append(f"-# ⚠️ Couldn't find experience `{code}` — check the code.")
    texts.append(f"-# scheduled by **<@{user_id}>**")
    return texts


def announcement_overhead(role_ids: Iterable[int]) -> int:
    """Worst-case length of everything in the announcement except the description.

    The description is the only unbounded part the scheduler controls, so summing
    the maxima of the static parts (header, code/regions, warning, footer) tells us
    how many characters are left for it. The experience block is left out: it is
    unknown while the modal is open, so :func:`build_announcement_view` trims the
    description against the real total instead.
    """
    mentions = [f"<@&{role_id}>" for role_id in role_ids]
    regions_line = (
        len("**Regions:** ")
        + sum(len(m) for m in mentions)
        + max(len(mentions) - 1, 0)  # single spaces between mentions
    )
    code_line = len("**Experience Code:** ``") + EXPERIENCE_CODE_MAX_LENGTH
    # Code and regions share one text display, joined by a newline.
    details = code_line + 1 + regions_line

    warning_line = (
        len("-# ⚠️ Couldn't find experience `` — check the code.")
        + EXPERIENCE_CODE_MAX_LENGTH
    )

    footer_line = len("-# scheduled by **<@>**") + MAX_SNOWFLAKE_DIGITS

    return _MAX_HEADER_LINE + details + warning_line + footer_line


def description_char_budget(role_ids: Iterable[int]) -> int:
    """How many description characters fit before the message exceeds the limit."""
    available = MAX_TEXT_CHARS - announcement_overhead(role_ids)
    return max(min(DESCRIPTION_MAX_LENGTH, available), 0)


def _fit_description(description: str, others: Iterable[str]) -> str:
    """Shorten the description until every text display fits the v2 text budget.

    The modal already caps the description, but the experience block is only known
    after the code is looked up, so a long description plus a long experience can
    still overshoot. Trimming here is the last line of defence: Discord rejects the
    whole message with a 400 otherwise.
    """
    budget = MAX_TEXT_CHARS - sum(len(text) for text in others)
    if len(description) <= budget:
        return description

    log.warning(
        "Trimming the playtest description by %s characters to fit the %s character"
        " components v2 budget",
        len(description) - budget,
        MAX_TEXT_CHARS,
    )
    return description[: max(budget - 1, 0)].rstrip() + "…"


async def get_announcement_channel(guild: discord.Guild | None) -> TextChannel | None:
    if not guild:
        return None
    try:
        channel_id = env.PLAYTEST_COG_SETTINGS.ANNOUNCE_CHANNEL_ID
        channel = guild.get_channel(channel_id) or await guild.fetch_channel(channel_id)
        assert isinstance(channel, TextChannel)
        return channel
    except AssertionError:
        log.exception("Announcement channel is not a TextChannel")

    return None


def build_announcement_view(
    *,
    user_id: int,
    seed: int,
    description: str,
    code: str,
    roles: list[discord.Role],
    experience: Experience | None = None,
) -> discord.ui.LayoutView:
    """Assemble the announcement as a components v2 layout.

    ``seed`` drives the header and accent so a playtest keeps the same look across
    edits; callers pass the message id once the message exists.

    Order: header, the looked-up experience beside its thumbnail (so the body reads
    as a comment on it), the description, then the code, the region pings and the
    scheduler.
    """
    header = header_text(seed)
    metas = meta_texts(code, roles, user_id, experience)
    block = experience_block(experience) if experience is not None else None
    image = experience.image if experience is not None else None

    others = [header, *metas] + ([block] if block else [])
    description = _fit_description(description, others)

    children: list[discord.ui.Item] = [
        discord.ui.TextDisplay(header),
        discord.ui.Separator(),
    ]
    if block and image:
        # The experience is the only block with an image, so it is the one that can
        # be a section; without an image it stays a plain text display, since a
        # section must have an accessory.
        children.append(
            discord.ui.Section(
                discord.ui.TextDisplay(block),
                accessory=discord.ui.Thumbnail(
                    image, description=experience.name[:256]
                ),
            )
        )
        children.append(discord.ui.Separator())
    elif block:
        children.append(discord.ui.TextDisplay(block))
        children.append(discord.ui.Separator())
    children.append(discord.ui.TextDisplay(description))
    children.append(discord.ui.Separator())
    children.extend(discord.ui.TextDisplay(text) for text in metas)

    view = discord.ui.LayoutView(timeout=None)
    view.add_item(
        discord.ui.Container(*children, accent_colour=pick_accent(seed)),
    )

    count = sum(1 for _ in view.walk_children())
    if count > MAX_COMPONENTS:
        log.error(
            "Playtest announcement uses %s components, over the limit of %s",
            count,
            MAX_COMPONENTS,
        )
    return view


async def send_announcement(
    user_id: int,
    channel: discord.abc.Messageable,
    roles: list[discord.Role],
    description: str,
    code: str,
    experience: Experience | None = None,
) -> discord.Message:
    """Post the announcement as a components v2 layout."""
    mentions = discord.AllowedMentions(roles=roles or False)
    # Post first so the message exists (its id also becomes the id of the thread
    # created from it), then re-render the header seeded on that id for a stable,
    # per-playtest header. Editing does not re-ping the roles.
    view = build_announcement_view(
        user_id=user_id,
        seed=user_id,
        description=description,
        code=code,
        roles=roles,
        experience=experience,
    )
    message = await channel.send(view=view, allowed_mentions=mentions)
    view = build_announcement_view(
        user_id=user_id,
        seed=message.id,
        description=description,
        code=code,
        roles=roles,
        experience=experience,
    )
    await message.edit(view=view, allowed_mentions=mentions)
    return message


async def update_announcement(
    user_id: int,
    message: discord.Message,
    roles: list[discord.Role],
    description: str,
    code: str,
    experience: Experience | None = None,
) -> None:
    """Re-render the announcement in place."""
    view = build_announcement_view(
        user_id=user_id,
        seed=message.id,
        description=description,
        code=code,
        roles=roles,
        experience=experience,
    )
    # Announcements posted before the layout existed still carry their text in the
    # message content, which has to be cleared in the same request that turns the
    # message into a components v2 one (setting that flag cannot be undone). Sending
    # content=None on a message that is already v2 is unnecessary, so only send it
    # when there is text to remove.
    extra = {} if message.flags.components_v2 else {"content": None}
    await message.edit(
        view=view,
        allowed_mentions=discord.AllowedMentions(roles=roles or False),
        **extra,
    )
