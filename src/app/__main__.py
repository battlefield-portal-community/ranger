"""Entry point: configure logging and run the bot."""

from __future__ import annotations

import logging

from .bot import Ranger
from .config import env
from .tls import use_certifi


def start() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    # Before any client exists, so every TLS connection in the process uses it.
    use_certifi()
    bot = Ranger()
    logger = logging.getLogger(__name__)
    logger.info(f"Starting bot with config: {env.model_dump_json(indent=2)}")
    bot.run(env.BOT_SETTINGS.DISCORD_TOKEN.get_secret_value(), log_handler=None)


if __name__ == "__main__":
    start()
