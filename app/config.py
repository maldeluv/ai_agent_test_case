from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "browser_ai_agent"
    log_level: str = "INFO"
    max_steps: int = Field(default=30, ge=1)
    browser_profile_dir: Path = PROJECT_ROOT / "browser_profile"
    screenshots_dir: Path = PROJECT_ROOT / "screenshots"


@lru_cache
def get_settings() -> Settings:
    return Settings()
