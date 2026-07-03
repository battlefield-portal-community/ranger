"""Application settings, loaded from the environment via pydantic-settings.

The single ``env`` global is imported across the project, e.g.::

    from app.config import env
    token = env.BOT_SETTINGS.DISCORD_TOKEN
    channel = env.PLAYTEST_COG_SETTINGS.MENU_CHANNEL_ID

Environment variables use the nested delimiter ``__`` to address a nested
settings block, e.g. ``BOT_SETTINGS__DISCORD_TOKEN``,
``PLAYTEST_COG_SETTINGS__MENU_CHANNEL_ID``.
"""

from __future__ import annotations


import json
from dotenv import load_dotenv
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv()

class BotSettings(BaseModel):
    """Global, bot-wide settings."""

    DISCORD_TOKEN: SecretStr
    GUILD_ID: int = Field()
    DB_PATH: str = Field(default="ranger.db")
    LOG_LEVEL: str = Field(default="INFO")
    DEBUG: bool = Field(default=False)

    HEALTH_STATE_FILE: str = Field(default="/tmp/ranger.health")
    HEALTH_HEARTBEAT_INTERVAL: int = Field(default=15)
    HEALTH_STALE_THRESHOLD: int = Field(default=45)



class PlaytestCogSettings(BaseModel):
    """Settings owned by the playtest cog."""

    MENU_CHANNEL_ID: int
    ANNOUNCE_CHANNEL_ID: int
    REGIONS_CONFIG_DIR: str = "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__")

    BOT_SETTINGS: BotSettings
    PLAYTEST_COG_SETTINGS: PlaytestCogSettings


# Global singleton imported across the project.
env = Settings()


@lru_cache(maxsize=1)
def load_regions() -> dict[str, int]:
    """Load the curated region -> role-id mapping for the configured guild.

    The file is selected per-guild as ``<regions_config_dir>/regions.<guild_id>.json``
    so multiple guilds can each have their own region -> role mapping. The guild
    id comes from ``BOT_SETTINGS.GUILD_ID``.

    Returns an insertion-ordered mapping (region name -> Discord role id).
    """
    guild_id = env.BOT_SETTINGS.GUILD_ID
    path = Path(env.PLAYTEST_COG_SETTINGS.REGIONS_CONFIG_DIR) / f"regions.{guild_id}.json"
    raw = json.loads(path.read_text())
    return {str(name): int(role_id) for name, role_id in raw.items()}
