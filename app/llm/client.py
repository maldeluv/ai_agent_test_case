from __future__ import annotations

from app.config import Settings
from app.llm.claude_client import ClaudeClient
from app.llm.openai_client import OpenAIClient


def create_llm_client(settings: Settings) -> ClaudeClient | OpenAIClient:
    if settings.llm_provider == "openai":
        return OpenAIClient(settings)
    if settings.llm_provider == "anthropic":
        return ClaudeClient(settings)
    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")
