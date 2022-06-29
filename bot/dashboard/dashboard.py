import json
import os
import asyncio
import psycopg2
from loguru import logger
from ..utils.helper import project_base_path

try:
    from ..pgsql import ConnectionWrapper

    con = ConnectionWrapper()
    con.ensure_base_tables()
except psycopg2.OperationalError:
    raise

try:
    if not os.getenv('DB_DEBUG', None):
        from fastapi import FastAPI
        from bot.bot import Ranger

        app = FastAPI()

        bot = Ranger(debug_guilds=[
            int(os.getenv('GUILD_ID'))
        ], con_=con)
        bot.load_custom_cogs()


        @app.on_event("startup")
        async def startup():
            logger.debug("Starting Bot....")
            # asyncio.create_task(bot.start(os.getenv("DISCORD_TOKEN")))


        @app.get("/")
        async def read_root():
            return {"Hello": str(bot.user)}

        @app.get('/configs/get/')
        async def return_config(config: str):
            config_folder = project_base_path / "configs"
            if config in [json_file.stem for json_file in list(config_folder.glob("*.json"))]:
                with open(config_folder / f"{config}.json") as file:
                    return json.load(file)
            else:
                return {config: 'Invalid'}

        @app.get('/configs/get/schema')
        async def return_config(config: str):
            config_schema_folder = project_base_path / "configs" / "schemas"
            if f"{config}.schema" in [json_file.stem for json_file in list(config_schema_folder.glob("*.json"))]:
                with open(config_schema_folder / f"{config}.schema.json") as file:
                    return json.load(file)
            else:
                return {config: 'Invalid'}

        @app.get("/get/channel/")
        async def channel_name(id: int):
            channel = bot.get_channel(id)
            if channel:
                return {
                    'channel': {
                        'id': id,
                        'name': channel.name
                    }
                }
            else:
                return {'channel': {}}


except ConnectionError as e:
    logger.critical(f"Unable to connect to Discord. exit error {e}")
    raise
except ImportError:
    raise ImportError("Unable to import bot lib")
