from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic

from app.config import Settings


class ClaudeClient:
    def __init__(self, settings: Settings) -> None:
        if settings.anthropic_api_key is None:
            raise ValueError("ANTHROPIC_API_KEY is not configured")

        self.model = settings.anthropic_model
        self.max_tokens = settings.anthropic_max_tokens
        self._client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )

    async def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        return await self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )
