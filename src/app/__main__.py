"""Entry point: configure logging and run the bot."""

from __future__ import annotations

import logging
import json

from .bot import Ranger
from .config import env


def start() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    bot = Ranger()
    logger = logging.getLogger(__name__)
    logger.info(f"Starting bot with config: {json.dumps(env.model_dump(), indent=2, sort_keys=True)}")
    bot.run(env.BOT_SETTINGS.DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    start()
