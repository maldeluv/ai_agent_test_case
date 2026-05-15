from __future__ import annotations

from app.config import Settings


def test_blank_api_keys_are_treated_as_missing() -> None:
    settings = Settings(openai_api_key=" ", anthropic_api_key="")

    assert settings.openai_api_key is None
    assert settings.anthropic_api_key is None


def test_openai_is_default_llm_provider() -> None:
    settings = Settings()

    assert settings.llm_provider == "openai"
