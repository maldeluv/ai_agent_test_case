from __future__ import annotations

import json
from typing import Any

from app.tools.registry import ToolDefinition, ToolRegistry
from app.tools.schemas import ToolResult
from app.utils.truncate import truncate_text


def tool_definitions_for_provider(
    registry: ToolRegistry,
    provider: str,
) -> list[dict[str, Any]]:
    if provider == "openai":
        return tool_definitions_for_openai(registry)
    if provider == "anthropic":
        return tool_definitions_for_claude(registry)
    raise ValueError(f"Unsupported LLM provider: {provider}")


def tool_definitions_for_openai(registry: ToolRegistry) -> list[dict[str, Any]]:
    return [tool_definition_for_openai(tool) for tool in registry.list_tools()]


def tool_definition_for_openai(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.input_model.model_json_schema(),
    }


def tool_definitions_for_claude(registry: ToolRegistry) -> list[dict[str, Any]]:
    return [tool_definition_for_claude(tool) for tool in registry.list_tools()]


def tool_definition_for_claude(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_model.model_json_schema(),
    }


def content_block_to_dict(block: Any) -> dict[str, Any]:
    if isinstance(block, dict):
        return block
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)

    block_type = getattr(block, "type", None)
    if block_type == "text":
        return {"type": "text", "text": getattr(block, "text", "")}
    if block_type == "tool_use":
        return {
            "type": "tool_use",
            "id": getattr(block, "id"),
            "name": getattr(block, "name"),
            "input": getattr(block, "input", {}),
        }
    raise TypeError(f"Unsupported Claude content block: {type(block).__name__}")


def get_block_type(block: Any) -> str | None:
    if isinstance(block, dict):
        return block.get("type")
    return getattr(block, "type", None)


def get_block_text(block: Any) -> str:
    if isinstance(block, dict):
        return str(block.get("text", ""))
    return str(getattr(block, "text", ""))


def get_tool_use_id(block: Any) -> str:
    if isinstance(block, dict):
        return str(block["id"])
    return str(getattr(block, "id"))


def get_tool_use_name(block: Any) -> str:
    if isinstance(block, dict):
        return str(block["name"])
    return str(getattr(block, "name"))


def get_tool_use_input(block: Any) -> dict[str, Any]:
    raw_input = block.get("input", {}) if isinstance(block, dict) else getattr(block, "input", {})
    return raw_input if isinstance(raw_input, dict) else {}


def tool_result_block(tool_use_id: str, result: ToolResult) -> dict[str, Any]:
    payload = result.model_dump(mode="json", exclude_none=True)
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": truncate_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            max_chars=8000,
        ),
        "is_error": not result.ok,
    }
