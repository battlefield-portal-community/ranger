"""Entry point: configure logging and run the bot."""

from __future__ import annotations

import logging

from .bot import Ranger
from .config import env


def start() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    bot = Ranger()
    bot.run(env.BOT_SETTINGS.discord_token, log_handler=None)


if __name__ == "__main__":
    start()
