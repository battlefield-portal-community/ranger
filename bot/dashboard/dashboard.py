import json
import os
import asyncio
from pathlib import Path

import psycopg2
from loguru import logger
from ..utils.helper import project_base_path, configs_path

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

        if os.getenv('DEBUG_SERVER', '').lower() != 'true':
            bot = Ranger(debug_guilds=[
                int(os.getenv('GUILD_ID'))
            ], con_=con)
            bot.load_custom_cogs()


        @app.on_event("startup")
        async def startup():
            logger.debug("Starting Bot....")
            if os.getenv('DEBUG_SERVER', '').lower() != 'true':
                asyncio.create_task(bot.start(os.getenv("DISCORD_TOKEN")))
            else:
                logger.debug("Server Debugging turned on... skipping starting bot")


        @app.get("/", response_class=HTMLResponse)
        async def read_root(request: Request):
            if files := await get_files('global_config'):
                with open(files[0]) as config_file, open(files[1]) as schema_file:
                    config, schema = json.load(config_file), json.load(schema_file)

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
            if files := await get_files(config):
                with open(files[0]) as config_file, open(files[1]) as schema_file:
                    saved_config, schema = json.load(config_file), json.load(schema_file)

            return templates.TemplateResponse(
                "config_editor.html",
                {
                    'request': request,
                    'schema': schema,
                    'start_val': saved_config
                }
            )

        async def return_file(config_name: str, config: bool = False, schema: bool = False) -> dict:
            if config or schema:
                if files := await get_files(config_name):
                    with open(files[0 if config else 1]) as file:
                        return json.load(file)
                else:
                    return {config: 'Invalid'}

        @app.get('/raw/configs')
        async def return_config(config: str):
            return await return_file(config, config=True)


        @app.get('/raw/configs/schema')
        async def return_schema(config: str) -> dict:
            return await return_file(config, schema=True)


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

        @app.post("/post/", status_code=201)
        async def save_config(request: Request, config: str):
            if files := await get_files(config):
                with open(files[0], 'w') as file:
                    json.dump(await request.json(), file, indent=2)
                    return {"saved": True}
            else:
                return {"saved": False, "config": False}

        async def get_files(config_name: str) -> tuple[Path, Path] | bool:
            schema_files = [config_file for config_file in list((configs_path / "schemas").glob("*.schema.json"))]
            if f"{config_name}.schema" in [file.stem for file in schema_files]:
                config_file = configs_path / f"{config_name}.json"
                confile_file_default = configs_path / "defaults" / f"{config_name}.json"
                if config_name != "definitions" and not config_file.exists():
                    config_file.touch()
                    default = dict()
                    if confile_file_default.exists():
                        with open(confile_file_default) as file:
                            default = json.load(file)

                    with open(config_file, 'w') as file:
                        json.dump(default, file)
                return config_file, configs_path / "schemas" / f"{config_name}.schema.json"
            else:
                return False


except ConnectionError as e:
    logger.critical(f"Unable to connect to Discord. exit error {e}")
    raise
except ImportError:
    raise ImportError("Unable to import bot lib")
