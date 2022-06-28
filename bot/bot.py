import discord
from loguru import logger
from discord.ext.commands import Bot

from .utils.helper import project_base_path
from .pgsql import ConnectionWrapper
from .cogs.cog_base import CogBase


class Ranger(Bot):
    def __init__(self, con_: ConnectionWrapper,  **options):
        intents = discord.Intents.default()
        super().__init__(intents=intents, **options)
        self.persistent_views_added = False
        self.con = con_
        self.cogs_list = [
            f"bot.cogs.{i.stem}"
            for i in (project_base_path / "cogs").glob("*.py")
            if i.name != "__init__.py"
        ]

    async def on_ready(self):
        if not self.persistent_views_added:
            logger.debug("Trying to re-register all views")
            # register views here

            for cog in self.cogs:
                cog_object: CogBase | discord.ext.commands.Cog
                cog_object = self.get_cog(cog)
                await cog_object.register_persistent_view()

        logger.debug("registration successful")
        self.persistent_views_added = True
        logger.info(f"Logged in as {self.user} - {self.user.id}")

    def load_custom_cogs(self):
        f"""
        Loads all the custom cogs defined in cogs/
        {self.cogs_list}
        :return:
        """
        logger.debug(f"Cogs to Load {len(self.cogs_list)}")
        if len(self.cogs_list) == 0:
            logger.critical("No cogs to load")
            return
        for cog in self.cogs_list:
            try:
                logger.debug(f"Trying to load {cog}")
                self.load_extension(cog)
            except BaseException as e:
                logger.critical(f"Failed Loading {cog} because of error {e}")
                raise
        logger.debug(f"Loading of all cogs successful")
