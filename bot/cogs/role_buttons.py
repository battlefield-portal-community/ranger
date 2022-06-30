import json
import aiofiles

import discord
from discord.ext import tasks
from loguru import logger

from .cog_base import CogBase
from ..utils.helper import project_base_path

from ..bot import Ranger


class Button(discord.ui.Button):
    def __init__(self,
                 label: str | None = None,
                 custom_id: str | None = None,
                 count: int | None = None,
                 emoji: str | None = None,
                 style: str | None = None,
                 role_id: int | None = None,
                 **kwargs
                 ):
        self.true_label = label
        self.count = count
        super().__init__(
            label=self.true_label + (f" ({self.count})" if self.count else ''),
            style=discord.ButtonStyle[style],
            emoji=emoji,
            custom_id=custom_id,
            row=kwargs.get('row', None)
        )
        self.role_id = int(role_id)

    async def callback(self, interaction: discord.Interaction):
        if self.role_id:
            role = interaction.guild.get_role(self.role_id)
            if not role:
                logger.debug(f"Role {self.role_id} not found in cache")
                role_list = await interaction.guild.fetch_roles()
                r = [r for r in role_list if r.id == self.role_id]
                if len(r):
                    role = r[0]
                else:
                    logger.debug(f"Role {self.role_id} not found in  guild {interaction.guild.id}")

            if role:
                await interaction.user.add_roles(role)
                if self.count is not None:
                    mem = interaction.guild.get_role(self.role_id).members
                    self.count = f"{len(mem)}"
                    self.label = self.true_label + f" ({self.count})"
                    await interaction.message.edit(embeds=interaction.message.embeds, view=self.view)
                await interaction.response.send_message("Successful", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Failed", ephemeral=True)
        else:
            pass


class RoleButtonsManger(CogBase):
    def __init__(self, bot_: Ranger):
        self.bot = bot_
        self.config_file_path = project_base_path / "configs/role_buttons.json"
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
        if self.config:
            for channel_ in self.config['channels']:

                if channel := self.bot.get_channel(int(channel_['id'])):
                    channel_['name'] = channel.name
                    for group in channel_['groups']:
                        if not group['disabled']:
                            message = group['message']
                            embeds = []
                            view = discord.ui.View(timeout=None)
                            for field, values in message.items():
                                if field == "embed":
                                    kwargs = values.copy()
                                    kwargs['color'] = int(values['color'][1:], 16)
                                    embeds.append(discord.Embed(**kwargs))
                                elif field == "buttons":
                                    count = values['count']
                                    for button_kwargs in values['list']:
                                        role_id = int(button_kwargs['role_id'])
                                        if role := channel.guild.get_role(role_id):
                                            view.add_item(
                                                Button(
                                                    **button_kwargs,
                                                    custom_id=f"{role_id}",
                                                    count=len(role.members) if count else None,
                                                )
                                            )
                                        else:
                                            logger.debug(f"Invalid Role {role_id} passed in json")
                            if "id" in message.keys():
                                try:
                                    msg_id = message['id']
                                    msg = await channel.get_partial_message(msg_id).fetch()
                                    if self.applied_config != self.config:
                                        await msg.edit(embeds=embeds, view=view)
                                except discord.NotFound or discord.Forbidden:
                                    msg = await channel.send(embeds=embeds, view=view)
                                    msg_id = msg.id
                            else:
                                msg = await channel.send(embeds=embeds, view=view)
                                msg_id = msg.id
                            if not self.bot.persistent_views_added:
                                self.bot.add_view(view=view, message_id=msg_id)
                            message['id'] = str(msg_id)

            for file_path in [self.config_file_path, self.applied_config_path]:
                with open(file_path, 'w') as file:
                    json.dump(self.config, file, sort_keys=True, indent=2)
            self.applied_config = self.config.copy()

    @tasks.loop(seconds=10)
    async def watch_config(self):
        async with aiofiles.open(self.config_file_path) as file:
            json_data = await file.read()
        tmp = json.loads(json_data)
        if tmp != self.config:
            logger.debug("role buttons config changed reloading")
            self.config = tmp
            await self.make_message()

    @watch_config.before_loop
    async def before(self):
        await self.bot.wait_until_ready()


def setup(bot: Ranger):
    bot.add_cog(RoleButtonsManger(bot))
