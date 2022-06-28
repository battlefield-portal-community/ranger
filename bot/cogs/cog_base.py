from discord.ext import commands


class CogBase(commands.Cog):

    async def register_persistent_view(self):
        pass


def setup(bot):
    pass
