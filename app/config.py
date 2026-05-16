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
    browser_action_timeout_ms: int = Field(default=7000, ge=500, le=60000)
    browser_new_tab_timeout_ms: int = Field(default=4000, ge=0, le=60000)
    browser_ui_settle_ms: int = Field(default=700, ge=0, le=10000)
    browser_load_state_timeout_ms: int = Field(default=1500, ge=100, le=15000)
    llm_provider: Literal["openai", "anthropic"] = "openai"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.4-mini"
    openai_max_output_tokens: int = Field(default=4096, ge=256, le=128000)
    openai_use_previous_response_id: bool = False
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
    content_max_items: int = Field(default=40, ge=1, le=200)
    content_max_text_chars: int = Field(default=700, ge=80, le=3000)
    content_max_controls_per_item: int = Field(default=8, ge=0, le=30)
    content_max_total_chars: int = Field(default=22000, ge=2000, le=160000)
    content_query_payload_max_chars: int = Field(default=24000, ge=2000, le=160000)
    vision_observation_enabled: bool = True
    vision_screenshot_quality: int = Field(default=70, ge=30, le=95)
    vision_max_screenshot_bytes: int = Field(default=3_000_000, ge=50_000, le=20_000_000)
    vision_question_max_chars: int = Field(default=1000, ge=100, le=5000)

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
