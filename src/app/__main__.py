"""Entry point: configure logging and run the bot."""

from __future__ import annotations

import asyncio
import logging
import signal

from .bot import Ranger
from .config import env

# Both are delivered to the process: Ctrl+C sends SIGINT, ``docker stop`` and a
# redeploy send SIGTERM.
TERMINATION_SIGNALS = (signal.SIGINT, signal.SIGTERM)

log = logging.getLogger(__name__)


async def serve(bot: Ranger) -> None:
    """Run the bot until it is interrupted or the connection closes."""
    async with bot:
        await bot.start(env.BOT_SETTINGS.DISCORD_TOKEN.get_secret_value())


def interrupt(signum: int, _frame: object) -> None:
    """Turn a termination signal into a :class:`KeyboardInterrupt`.

    ``discord.Client.run`` lets a SIGINT unwind quietly, and ``asyncio`` only
    installs its own handler when the signal still has the default one, so the
    handler is set here instead: both signals then take the same path out, and
    ``start`` can report the shutdown rather than the process just vanishing.
    """
    raise KeyboardInterrupt(signal.Signals(signum).name)


def start() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info(f"Starting bot with config: {env.model_dump_json(indent=2)}")
    for signum in TERMINATION_SIGNALS:
        signal.signal(signum, interrupt)
    bot = Ranger()
    try:
        asyncio.run(serve(bot))
    except KeyboardInterrupt as exc:
        logger.info("Received %s: Ranger has shut down", exc)


if __name__ == "__main__":
    start()
