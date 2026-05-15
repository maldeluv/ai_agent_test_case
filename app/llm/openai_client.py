from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from openai import AsyncOpenAI

from app.config import Settings


class OpenAIClient:
    def __init__(self, settings: Settings) -> None:
        if settings.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is not configured")

        self.model = settings.openai_model
        self.max_output_tokens = settings.openai_max_output_tokens
        self._client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
        self._previous_response_id: str | None = None

    async def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        input_items = self._build_input_items(messages)
        request: dict[str, Any] = {
            "model": self.model,
            "instructions": system,
            "input": input_items,
            "max_output_tokens": self.max_output_tokens,
        }
        if tools:
            request["tools"] = tools
            request["parallel_tool_calls"] = False
        if self._previous_response_id is not None:
            request["previous_response_id"] = self._previous_response_id

        response = await self._client.responses.create(**request)
        self._previous_response_id = response.id
        return SimpleNamespace(content=self._content_blocks_from_response(response))

    def _build_input_items(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._previous_response_id is None:
            first_message = messages[0] if messages else {"role": "user", "content": ""}
            return [
                {
                    "role": "user",
                    "content": str(first_message.get("content", "")),
                }
            ]

        last_message = messages[-1] if messages else {}
        content = last_message.get("content", [])
        if not isinstance(content, list):
            return [{"role": "user", "content": str(content)}]

        input_items = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": block["tool_use_id"],
                        "output": str(block.get("content", "")),
                    }
                )
            elif block.get("type") == "text":
                input_items.append(
                    {
                        "role": "user",
                        "content": str(block.get("text", "")),
                    }
                )
        return input_items

    def _content_blocks_from_response(self, response: Any) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        output = getattr(response, "output", []) or []

        for item in output:
            item_type = self._get_attr(item, "type")
            if item_type == "message":
                text = self._message_text(item)
                if text:
                    blocks.append({"type": "text", "text": text})
            elif item_type == "function_call":
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(self._get_attr(item, "call_id")),
                        "name": str(self._get_attr(item, "name")),
                        "input": self._parse_arguments(
                            self._get_attr(item, "arguments", "{}")
                        ),
                    }
                )

        if not blocks:
            output_text = getattr(response, "output_text", "")
            if output_text:
                blocks.append({"type": "text", "text": output_text})
        return blocks

    def _message_text(self, message: Any) -> str:
        chunks: list[str] = []
        for content in self._get_attr(message, "content", []) or []:
            content_type = self._get_attr(content, "type")
            if content_type in {"output_text", "text"}:
                text = self._get_attr(content, "text", "")
                if text:
                    chunks.append(str(text))
        return "\n".join(chunks).strip()

    def _parse_arguments(self, raw_arguments: Any) -> dict[str, Any]:
        if isinstance(raw_arguments, dict):
            return raw_arguments
        if not raw_arguments:
            return {}
        try:
            parsed = json.loads(str(raw_arguments))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _get_attr(self, value: Any, name: str, default: Any = None) -> Any:
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)
