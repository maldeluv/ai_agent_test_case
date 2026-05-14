from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
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
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-4-20250514"
    anthropic_max_tokens: int = Field(default=4096, ge=256, le=64000)
    browser_profile_dir: Path = PROJECT_ROOT / "browser_profile"
    screenshots_dir: Path = PROJECT_ROOT / "screenshots"
    viewport_width: int = Field(default=1280, ge=320)
    viewport_height: int = Field(default=900, ge=240)

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def empty_secret_to_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @field_validator("browser_profile_dir", "screenshots_dir")
    @classmethod
    def resolve_project_path(cls, value: Path) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return PROJECT_ROOT / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
