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
        self._use_previous_response_id = settings.openai_use_previous_response_id
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
        if self._use_previous_response_id and self._previous_response_id is not None:
            request["previous_response_id"] = self._previous_response_id

        response = await self._client.responses.create(**request)
        if self._use_previous_response_id:
            self._previous_response_id = response.id
        return SimpleNamespace(content=self._content_blocks_from_response(response))

    def _build_input_items(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        use_previous_response_id = getattr(
            self,
            "_use_previous_response_id",
            getattr(self, "_previous_response_id", None) is not None,
        )
        if use_previous_response_id:
            return self._build_input_items_for_previous_response(messages)

        input_items: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role", "user"))
            content = message.get("content", "")
            if isinstance(content, list):
                input_items.extend(self._content_list_to_input_items(role, content))
            else:
                input_items.append({"role": role, "content": str(content)})
        return input_items or [{"role": "user", "content": ""}]

    def _build_input_items_for_previous_response(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
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

    def _content_list_to_input_items(
        self,
        role: str,
        content: list[Any],
    ) -> list[dict[str, Any]]:
        input_items: list[dict[str, Any]] = []
        text_chunks: list[str] = []
        multimodal_content: list[dict[str, str]] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "tool_result":
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": block["tool_use_id"],
                        "output": str(block.get("content", "")),
                    }
                )
            elif block_type == "tool_use":
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": str(block.get("id", "")),
                        "name": str(block.get("name", "")),
                        "arguments": json.dumps(
                            block.get("input", {}),
                            ensure_ascii=False,
                        ),
                    }
                )
            elif block_type == "text":
                text = str(block.get("text", ""))
                if text:
                    text_chunks.append(text)
            elif block_type == "image":
                image_content = self._image_block_to_openai_content(block)
                if image_content is not None:
                    multimodal_content.append(image_content)

        if multimodal_content:
            message_content = [
                {"type": "input_text", "text": "\n".join(text_chunks)}
            ] if text_chunks else []
            message_content.extend(multimodal_content)
            input_items.append(
                {
                    "role": role if role in {"user", "assistant", "system"} else "user",
                    "content": message_content,
                }
            )
        elif text_chunks:
            input_items.append(
                {
                    "role": role if role in {"user", "assistant", "system"} else "user",
                    "content": "\n".join(text_chunks),
                }
            )
        return input_items

    def _image_block_to_openai_content(
        self,
        block: dict[str, Any],
    ) -> dict[str, str] | None:
        source = block.get("source")
        media_type = str(block.get("media_type") or "image/png")
        data = block.get("data")
        if isinstance(source, dict):
            media_type = str(source.get("media_type") or media_type)
            data = source.get("data", data)
        if not data:
            return None
        return {
            "type": "input_image",
            "image_url": f"data:{media_type};base64,{data}",
        }

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
