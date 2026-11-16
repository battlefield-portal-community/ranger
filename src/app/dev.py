"""Local development entry point: Ranger with hot reload.

``python -m app.dev`` (or ``uv run dev``) runs the bot exactly as ``python -m app``
does, and watches ``src/app`` for edits:

- a file under ``app/cogs/<name>`` reloads that extension in place: the gateway
  connection, the message caches and the database stay as they are, so a change to
  a menu, modal or command is live in well under a second. ``cog_unload`` cancels
  the cog's loops, ``cog_load`` re-registers its persistent views and restarts them,
  and discord.py rolls back atomically if the new version fails to import, so a
  half-written file leaves the previous one serving.
- anything else (``bot.py``, ``config.py``, ``db.py``, ``maps_data.py``, the cogs
  package itself) re-executes the process. Module-level state — the bot object, the
  cached database path, the loaded map table — cannot be swapped underneath the
  running bot, so this is a real restart: the pid survives and the gateway is only
  down for the second or two it takes to reconnect.

Production runs ``python -m app``, which knows nothing about any of this.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import signal
import sys
from dataclasses import dataclass
from pathlib import Path

import discord
from watchfiles import awatch

from .__main__ import TERMINATION_SIGNALS, interrupt, serve
from .bot import Ranger
from .config import env

log = logging.getLogger(__name__)

#: Everything the bot imports lives under here, so a save anywhere below it is seen.
APP_DIR = Path(__file__).parent

#: Cogs are discovered from this directory in :meth:`Ranger._load_cogs`.
COGS_DIR = "cogs"

#: A save is rarely one file (an editor may write a temp file, then move it), so a
#: burst is given time to settle before anything reloads.
DEBOUNCE_MS = 800

#: Long enough for the gateway close frame to leave before the process is replaced.
CLOSE_GRACE_SECONDS = 0.2

#: Bytecode caches under :data:`APP_DIR`, deleted once at startup.
BYTECODE_CACHE = "__pycache__"


def forget_bytecode() -> None:
    """Compile from source every time, and never write a ``.pyc``.

    A cached ``.pyc`` is validated against its source's mtime in whole seconds, so
    two saves inside the same second can hand a reload the previous bytecode and the
    edit looks ignored. Nothing here is being measured, so the cache goes and no
    replacement is written.
    """
    sys.dont_write_bytecode = True
    for cache in APP_DIR.rglob(BYTECODE_CACHE):
        shutil.rmtree(cache, ignore_errors=True)


@dataclass
class DevState:
    """What the watcher needs to act on, kept explicit instead of global."""

    bot: Ranger
    restart: bool = False


def extension_for(path: Path) -> str | None:
    """The extension owning ``path``, or ``None`` when it needs a full restart.

    ``app/cogs/maps.py`` and ``app/cogs/feedback/cog.py`` both belong to an
    extension; ``app/cogs/__init__.py`` is package plumbing, and everything outside
    ``app/cogs`` is core, which a reload cannot replace.
    """
    try:
        relative = path.relative_to(APP_DIR)
    except ValueError:
        return None

    parts = relative.parts
    if len(parts) < 2 or parts[0] != COGS_DIR:
        return None

    name = parts[1].removesuffix(".py")
    if name == "__init__":
        return None
    return f"app.{COGS_DIR}.{name}"


async def sync_commands(bot: Ranger) -> None:
    """Push the reloaded command set to the same guild ``setup_hook`` synced to.

    A reload leaves the guild's copies stale, so the tree is re-copied first. The
    sync is best effort: Discord rate limits command registration, and a skipped
    sync only means the previous definitions stay live until the next save.
    """
    guild = discord.Object(id=env.BOT_SETTINGS.GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    try:
        await bot.tree.sync(guild=guild)
    except discord.HTTPException:
        log.warning(
            "Could not re-sync the guild commands; the previous ones still work",
            exc_info=True,
        )


async def reload_extension(bot: Ranger, extension: str) -> None:
    """Reload one extension in place, keeping the connection."""
    try:
        await bot.reload_extension(extension)
    except Exception:
        log.exception(
            "Could not reload %s; the previous version stays loaded", extension
        )
        return

    log.info("Reloaded %s", extension)
    await sync_commands(bot)

    # A reloaded cog has never seen ``on_ready``, so the menu it ensures would wait
    # for the next colour-cycle tick. Replaying the event runs those listeners
    # again; they edit the message they already stored, so this is idempotent.
    bot.dispatch("ready")


async def restart(state: DevState) -> None:
    """Ask the process to re-exec itself once the bot has closed."""
    state.restart = True
    log.info("Core module changed: restarting the process")
    state.bot.close()
    await asyncio.sleep(CLOSE_GRACE_SECONDS)


async def watch(state: DevState) -> None:
    """Reload the extensions a save touched, or restart for anything else."""
    async for changes in awatch(APP_DIR, debounce=DEBOUNCE_MS):
        paths = {Path(path) for _, path in changes if path.endswith(".py")}
        if not paths:
            continue

        extensions: set[str] = set()
        for path in paths:
            extension = extension_for(path)
            if extension is None:
                await restart(state)
                return
            extensions.add(extension)

        # Sorted so a save that touches two cogs reloads them in a stable order.
        for extension in sorted(extensions):
            await reload_extension(state.bot, extension)


async def run(state: DevState) -> None:
    """Run the bot and its watcher side by side until either one stops."""
    watcher = asyncio.create_task(watch(state))
    try:
        await serve(state.bot)
    finally:
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher


def start() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    for signum in TERMINATION_SIGNALS:
        signal.signal(signum, interrupt)

    forget_bytecode()
    log.info("Watching %s for changes", APP_DIR)
    state = DevState(bot=Ranger())
    try:
        asyncio.run(run(state))
    except KeyboardInterrupt as exc:
        log.info("Received %s: Ranger has shut down", exc)
        return

    if not state.restart:
        return

    # Same interpreter, same arguments, same process: the sandbox, the pid and the
    # terminal stay as they are, only the imported modules start over.
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(sys.executable, [sys.executable, "-m", "app.dev", *sys.argv[1:]])


if __name__ == "__main__":
    start()
