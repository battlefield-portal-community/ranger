import json
import os
import asyncio
import secrets
from pathlib import Path

import dictdiffer
import discord
from loguru import logger
from ..utils.helper import project_base_path, configs_path, configs_base


# try:
#     from ..pgsql import ConnectionWrapper
#
#     con = ConnectionWrapper()
#     con.ensure_base_tables()
# except psycopg2.OperationalError:
#     raise


def ensure_defaults():
    logger.debug("Ensuring default config files")
    logger.debug(configs_base)
    for file in (configs_base / "defaults").glob("*.json"):
        write_defaults = False
        if not (config_file_path := configs_path / file.name).exists():
            config_file_path.touch()
            write_defaults = True
        elif config_file_path.stat().st_size == 0:
            write_defaults = True
        elif file.stem == "global_config":
            with file.open('r') as FILE:
                default_config = json.load(FILE)
            with config_file_path.open('r') as FILE:
                curr_config = json.load(FILE)
            default_config: dict
            curr_config: dict
            diff = list(dictdiffer.diff(curr_config, default_config))
            diff = [i for i in diff if i[0] != "change"]
            logger.debug(diff)
            dictdiffer.patch(diff, curr_config, in_place=True)
            with config_file_path.open('w') as FILE:
                json.dump(curr_config, FILE, indent=2)

        if write_defaults:
            with open(file) as default, open(config_file_path, 'w') as config:
                config.write(default.read())


try:
    if not os.getenv('DB_DEBUG', None):
        import re
        from fastapi import FastAPI, Request
        from fastapi.responses import HTMLResponse
        from fastapi.staticfiles import StaticFiles
        from fastapi.templating import Jinja2Templates
        from fastapi.middleware import Middleware
        from fastapi.middleware.cors import CORSMiddleware
        from starlette_discord import DiscordOAuthClient
        from starlette.middleware.sessions import SessionMiddleware
        from starlette.responses import RedirectResponse

        client_id = os.getenv("DISCORD_CLIENT_ID")
        client_secret = os.getenv("DISCORD_SECRET")
        redirect_uri = f"http://{os.getenv('SERVER_HOSTNAME')}:5000/login/callback"

        origins = [
            "http://vmi656705.contaboserver.net:5000",
            "https://vmi656705.contaboserver.net:5000",
            "https://gorgeous-ghouls.github.io",
            "http://0.0.0.0",
            "http://localhost",
            "http://0.0.0.0:8000",
            "http://localhost:5000"
        ],

        middleware = [
            Middleware(
                CORSMiddleware,
                allow_origins=origins,
                allow_credentials=True,
                allow_methods=['*'],
                allow_headers=['*']
            )
        ]

        app = FastAPI(middleware=middleware)
        discord_client = DiscordOAuthClient(client_id, client_secret, redirect_uri,
                                            scopes=("email", "identify", "guilds"))

        dashboard_root = project_base_path / "dashboard"
        static_path = dashboard_root / "static"
        app.mount(str(static_path), StaticFiles(directory=static_path), name="static")
        templates = Jinja2Templates(directory=dashboard_root / "templates")

        from bot.bot import Ranger

        if os.getenv('DEBUG_SERVER', '').lower() != 'true':
            bot = Ranger(debug_guilds=[
                int(os.getenv('GUILD_ID'))
            ])


        @app.on_event("startup")
        async def startup():
            ensure_defaults()  # blocking call
            await bot.load_custom_cogs()
            logger.debug("Starting Bot....")
            if os.getenv('DEBUG_SERVER', '').lower() != 'true':
                asyncio.create_task(bot.start(os.getenv("DISCORD_TOKEN")))
            else:
                logger.debug("Server Debugging turned on... skipping starting bot")


        @app.middleware('http')
        async def check_for_login(request: Request, call_next):
            no_login = ["/user"]
            if not any(map(lambda x: request.url.path.startswith(x), no_login)):
                if os.getenv('DEBUG_SERVER', '').lower() != 'true' and not request.url.path.startswith("/login") and request.session.get("discord_user", None) is None:
                    logger.debug("Not logged in")
                    return RedirectResponse("/login")
                else:
                    return await call_next(request)
            else:
                return await call_next(request)


        @app.get('/login')
        async def start_login():
            return discord_client.redirect()


        @app.get('/login/callback')
        async def finish_login(request: Request, code: str):
            async with discord_client.session(code) as session:
                user = await session.identify()
                guilds = await session.guilds()

            logger.debug(f"user {user} with id {user.id} logged in....")
            if int(os.getenv("GUILD_ID")) in [guild.id for guild in guilds]:
                for guild in guilds:
                    if int(os.getenv("GUILD_ID")) == guild.id and (guild.permissions & 0x0000000000000008):
                        logger.debug(f"{user} is a admin")
                        request.session["discord_user"] = str(user)
                        return RedirectResponse("/")
            else:
                return None


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


        # @bot.event
        # async def on_presence_update(before: discord.Member, after: discord.Member):
        #     logger.debug((before.status, after.status))


        @app.get('/user/')
        async def get_user_info(id: int, guild_id: int):
            guild = bot.get_guild(guild_id)
            logger.debug(guild.name)
            user = None
            if guild:
                user = guild.get_member(id)
                # user = guild.get_member(id)
            if user:
                return {
                    "status": True,
                    "schemaVersion": 1,
                    "label": "",
                    "message": user.status[0],
                    "color": "black",
                    "style": "for-the-badge"
                }
            else:
                return {'status': False}


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
            schema_files = [config_file for config_file in list((configs_base / "schemas" / "ranger").glob("*.schema.json"))]
            if f"{config_name}.schema" in [file.stem for file in schema_files]:
                config_file = configs_path / f"{config_name}.json"
                confile_file_default = configs_base / "defaults" / f"{config_name}.json"
                if config_name != "definitions" and not config_file.exists():
                    config_file.touch()
                    default = dict()
                    if confile_file_default.exists():
                        with open(confile_file_default) as file:
                            default = json.load(file)

                    with open(config_file, 'w') as file:
                        json.dump(default, file)
                return config_file, configs_base / "schemas" / "ranger" / f"{config_name}.schema.json"
            else:
                return False
        app.add_middleware(SessionMiddleware, secret_key=secrets.token_urlsafe(64))

except ConnectionError as e:
    logger.critical(f"Unable to connect to Discord. exit error {e}")
    raise
except ImportError as error:
    raise ImportError(f"Unable to import bot lib {error}")
