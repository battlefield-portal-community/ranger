"""Import an exported forum history into the feedback dedupe index.

Run once, with the bot's database and feedback settings in the environment::

    python -m app.seed_feedback <export-dir>

Every ``*.json`` in the directory is read as one DiscordChatExporter channel
export; files for other channels are ignored. A thread under the bug or feature
forum becomes one ``feedback_posts`` row (plus an FTS entry), so the archived posts
are searchable by the dedupe preflight. Rows already present are left alone, which
makes the import safe to re-run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from . import db
from .cogs.feedback import tags
from .config import env

log = logging.getLogger(__name__)


def _forum_id(channel: dict) -> int:
    parent = channel.get("parent") or channel.get("parentId") or 0
    if isinstance(parent, dict):
        return int(parent.get("id") or 0)
    return int(parent)


def _tag_names(channel: dict) -> list[str]:
    """Applied tag names, tolerating the spellings exporters use."""
    raw = (
        channel.get("appliedTags")
        or channel.get("applied_tags")
        or channel.get("tags")
        or []
    )
    names: list[str] = []
    for tag in raw:
        name = tag.get("name") if isinstance(tag, dict) else tag
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _kind(forum_id: int) -> str | None:
    settings = env.FEEDBACK_COG_SETTINGS
    if settings is None:
        raise SystemExit(
            "FEEDBACK_COG_SETTINGS__MENU_CHANNEL_ID must be set to map forums"
        )
    if forum_id == settings.BUG_FORUM_ID:
        return "bug"
    if forum_id == settings.FEATURE_FORUM_ID:
        return "feature"
    return None


def _epoch(value: str | None) -> int:
    if not value:
        return int(time.time())
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def _starter_message(messages: list[dict], channel_id: str) -> dict:
    """The forum starter message shares its id with the thread."""
    for message in messages:
        if str(message.get("id")) == str(channel_id):
            return message
    return messages[0]


def post_from_export(payload: dict) -> dict | None:
    """Turn one channel export into ``create_feedback`` arguments, or None."""
    channel = payload.get("channel") or {}
    messages = payload.get("messages") or []
    if not channel or not messages:
        return None
    forum_id = _forum_id(channel)
    kind = _kind(forum_id)
    if kind is None:
        return None

    starter = _starter_message(messages, channel.get("id", ""))
    # A thread's owner is Ranger, so the report's author is the only reporter we
    # can recover from an export.
    owner = channel.get("ownerId") or (channel.get("owner") or {}).get("id")
    reporter = owner or (starter.get("author") or {}).get("id") or "0"
    return {
        "thread_id": int(channel["id"]),
        "forum_id": forum_id,
        "kind": kind,
        "reporter_id": str(reporter),
        "summary": channel.get("name") or "Untitled",
        "body": starter.get("content") or "",
        # The export carries the status tags the thread had when it was dumped.
        "status": tags.status_from_tags(_tag_names(channel)),
        "created_at": _epoch(starter.get("timestamp")),
    }


async def seed(export_dir: Path) -> tuple[int, int]:
    """Index every exported forum thread, returning (inserted, skipped)."""
    await db.init_db(env.BOT_SETTINGS.DB_PATH)
    inserted = 0
    skipped = 0
    for path in sorted(export_dir.rglob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except OSError, json.JSONDecodeError:
            log.exception("Skipping unreadable export %s", path)
            continue
        post = post_from_export(payload)
        if post is None:
            continue
        if not await db.create_feedback(**post):
            skipped += 1
            continue
        await db.index_feedback(post["thread_id"], post["summary"], post["body"])
        inserted += 1
    return inserted, skipped


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Index an exported forum history into the dedupe database."
    )
    parser.add_argument("export_dir", type=Path, help="DiscordChatExporter export dir")
    args = parser.parse_args()
    if not args.export_dir.is_dir():
        parser.error(f"{args.export_dir} is not a directory")

    logging.basicConfig(level=env.BOT_SETTINGS.LOG_LEVEL)
    inserted, skipped = asyncio.run(seed(args.export_dir))
    log.info("Indexed %s feedback posts (%s already known)", inserted, skipped)


if __name__ == "__main__":
    main()
