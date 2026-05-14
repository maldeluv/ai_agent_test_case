from __future__ import annotations

from app.config import Settings


def test_blank_anthropic_api_key_is_treated_as_missing() -> None:
    settings = Settings(anthropic_api_key="")

    assert settings.anthropic_api_key is None
