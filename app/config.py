from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    max_consecutive_failures: int = Field(default=4, ge=1, le=20)
    agent_recent_actions_limit: int = Field(default=8, ge=1, le=50)
    agent_execution_summary_max_chars: int = Field(default=3000, ge=200, le=20000)
    agent_action_max_chars: int = Field(default=600, ge=100, le=5000)
    tool_result_max_chars: int = Field(default=6000, ge=500, le=50000)
    short_visible_text_chars: int = Field(default=2000, ge=200, le=10000)
    llm_provider: Literal["openai", "anthropic"] = "openai"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.4-mini"
    openai_max_output_tokens: int = Field(default=4096, ge=256, le=128000)
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-4-20250514"
    anthropic_max_tokens: int = Field(default=4096, ge=256, le=64000)
    browser_profile_dir: Path = PROJECT_ROOT / "browser_profile"
    screenshots_dir: Path = PROJECT_ROOT / "screenshots"
    viewport_width: int = Field(default=1280, ge=320)
    viewport_height: int = Field(default=900, ge=240)
    dom_max_elements: int = Field(default=80, ge=1, le=500)
    dom_max_text_chars: int = Field(default=160, ge=20, le=1000)
    dom_max_total_chars: int = Field(default=12000, ge=1000, le=100000)
    dom_query_payload_max_chars: int = Field(default=14000, ge=1000, le=120000)

    @field_validator("openai_api_key", "anthropic_api_key", mode="before")
    @classmethod
    def empty_secret_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("browser_profile_dir", "screenshots_dir")
    @classmethod
    def resolve_project_path(cls, value: Path) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return PROJECT_ROOT / path

    def has_active_llm_api_key(self) -> bool:
        if self.llm_provider == "openai":
            return self.openai_api_key is not None
        return self.anthropic_api_key is not None


@lru_cache
def get_settings() -> Settings:
    return Settings()
