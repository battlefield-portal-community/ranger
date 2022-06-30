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
        from fastapi import FastAPI, Request
        from fastapi.responses import HTMLResponse
        from fastapi.staticfiles import StaticFiles
        from fastapi.templating import Jinja2Templates

        from bot.bot import Ranger

        app = FastAPI()
        dashboard_root = project_base_path / "dashboard"
        static_path = dashboard_root / "static"
        app.mount(str(static_path), StaticFiles(directory=static_path), name="static")
        templates = Jinja2Templates(directory=dashboard_root / "templates")

        bot = Ranger(debug_guilds=[
            int(os.getenv('GUILD_ID'))
        ], con_=con)
        bot.load_custom_cogs()


        @app.on_event("startup")
        async def startup():
            logger.debug("Starting Bot....")
            # asyncio.create_task(bot.start(os.getenv("DISCORD_TOKEN")))


        @app.get("/", response_class=HTMLResponse)
        async def read_root(request: Request):
            with open(project_base_path / "configs" / "schemas" / "global_config.schema.json") as file:
                schema = json.load(file)
            with open(project_base_path / "configs" / "global_config.json") as file:
                config = json.load(file)
            return templates.TemplateResponse(
                "index.html",
                {
                    'request': request,
                    'schema': schema,
                    'start_val': config
                }
            )


        @app.get('/configs/', response_class=HTMLResponse)
        async def return_config(request: Request, config: str):
            with open(project_base_path / "configs" / "schemas" / f"{config}.schema.json") as file:
                schema = json.load(file)
            with open(project_base_path / "configs" / f"{config}.json") as file:
                saved_config = json.load(file)
            return templates.TemplateResponse(
                "config_editor.html",
                {
                    'request': request,
                    'schema': schema,
                    'start_val': saved_config
                }
            )

        @app.get('/raw/configs')
        async def return_config(config: str):
            config_folder = project_base_path / "configs"
            if config in [json_file.stem for json_file in list(config_folder.glob("*.json"))]:
                with open(config_folder / f"{config}.json") as file:
                    return json.load(file)
            else:
                return {config: 'Invalid'}


        @app.get('/raw/configs/schema')
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
