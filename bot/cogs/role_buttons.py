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
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        if self.role_id:
            await interaction.user.add_roles(interaction.guild.get_role(self.role_id))
            if self.count is not None:
                mem = interaction.guild.get_role(self.role_id).members
                self.count = f"{len(mem)}"
                self.label = self.true_label + f" ({self.count})"
                await interaction.message.edit(embeds=interaction.message.embeds, view=self.view)
            await interaction.response.send_message("Successful", ephemeral=True)
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
            for channel_id, groups in self.config.items():
                if channel := self.bot.get_channel(int(channel_id)):
                    for group_name, group in groups.items():
                        if not group['disabled']:
                            message = group['message']
                            embeds = []
                            view = discord.ui.View(timeout=None)
                            for field, values in message.items():
                                if field == "embed":
                                    embeds.append(discord.Embed(**values))
                                elif field == "buttons":
                                    count = values['count']
                                    for button_kwargs in values['list']:
                                        role_id = button_kwargs['role_id']
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
                            message['id'] = msg_id

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
            self.config = tmp
            await self.make_message()

    @watch_config.before_loop
    async def before(self):
        await self.bot.wait_until_ready()


def setup(bot: Ranger):
    bot.add_cog(RoleButtonsManger(bot))
