"""Application settings, loaded from the environment via pydantic-settings.

The single ``env`` global is imported across the project, e.g.::

    from app.config import env
    token = env.BOT_SETTINGS.discord_token
    channel = env.PLAYTEST_COG_SETTINGS.menu_channel_id

Environment variables use the nested delimiter ``__`` to address a nested
settings block, e.g. ``BOT_SETTINGS__DISCORD_TOKEN``,
``PLAYTEST_COG_SETTINGS__MENU_CHANNEL_ID``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseModel):
    """Global, bot-wide settings."""

    discord_token: str
    guild_id: int
    db_path: str = "ranger.db"


class PlaytestCogSettings(BaseModel):
    """Settings owned by the playtest cog."""

    menu_channel_id: int
    announce_channel_id: int
    regions_config_dir: str = "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    BOT_SETTINGS: BotSettings
    PLAYTEST_COG_SETTINGS: PlaytestCogSettings


# Global singleton imported across the project.
env = Settings()


@lru_cache(maxsize=1)
def load_regions() -> dict[str, int]:
    """Load the curated region -> role-id mapping for the configured guild.

    The file is selected per-guild as ``<regions_config_dir>/regions.<guild_id>.json``
    so multiple guilds can each have their own region -> role mapping. The guild
    id comes from ``BOT_SETTINGS.guild_id``.

    Returns an insertion-ordered mapping (region name -> Discord role id).
    """
    guild_id = env.BOT_SETTINGS.guild_id
    path = Path(env.PLAYTEST_COG_SETTINGS.regions_config_dir) / f"regions.{guild_id}.json"
    raw = json.loads(path.read_text())
    return {str(name): int(role_id) for name, role_id in raw.items()}
