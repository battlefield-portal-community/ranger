import json
import aiofiles

import discord
from discord.ext import tasks
from loguru import logger

from .cog_base import CogBase
from ..utils.helper import project_base_path

from ..bot import Ranger


class EmbedMessageManager(CogBase):
    def __init__(self, bot_: Ranger):
        self.bot = bot_
        self.config_file_path = project_base_path / "configs/embed_message.json"
        self.applied_config_path = self.config_file_path.parent / "applied_configs" / self.config_file_path.name

        self.applied_config_path.touch(exist_ok=True)
        with open(self.applied_config_path) as file:
            json_raw = file.read()
            if len(json_raw):
                self.applied_config = json.loads(json_raw)
            else:
                self.applied_config = dict()

        self.config = None
        self.config_file_path.touch(exist_ok=True)
        with open(self.config_file_path) as json_file:
            self.config = json.load(json_file)

        self.watch_config.start()

    async def register_persistent_view(self):
        if self.config and not self.bot.persistent_views_added:
            await self.make_message()

    async def make_message(self):
        if self.bot.config['cogs']['embed_message']['enabled']:
            if self.config:
                for channel_ in self.config['channels']:
                    if channel := self.bot.get_channel(int(channel_['id'])):
                        channel_['name'] = channel.name
                        embeds = []
                        embed: dict
                        for embed in channel_['embeds']:
                            kwargs = embed.copy()
                            kwargs.pop('name')
                            kwargs['color'] = int(embed['color'][1:], 16)
                            embeds.append(discord.Embed(**kwargs))
                        if embeds:
                            await channel.send(embeds=embeds)

                for file_path in [self.config_file_path, self.applied_config_path]:
                    with open(file_path, 'w') as file:
                        json.dump(self.config, file, sort_keys=True, indent=2)
                self.applied_config = self.config.copy()

            else:
                pass
        else:
            logger.debug(f"{self.qualified_name} is disabled in global config....skipping update..")

    @tasks.loop(seconds=10)
    async def watch_config(self):
        async with aiofiles.open(self.config_file_path) as file:
            json_data = await file.read()
        tmp = json.loads(json_data)
        if tmp != self.config:
            logger.debug("embed message config changed reloading")
            self.config = tmp
            await self.make_message()

    @watch_config.before_loop
    async def before(self):
        await self.bot.wait_until_ready()


def setup(bot: Ranger):
    bot.add_cog(EmbedMessageManager(bot))
