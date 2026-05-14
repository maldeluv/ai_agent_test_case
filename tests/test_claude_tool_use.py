from __future__ import annotations

import json

from app.llm.tool_use import tool_definitions_for_claude, tool_result_block
from app.tools.registry import create_default_tool_registry
from app.tools.schemas import ToolResult


def test_tool_definitions_for_claude_include_input_schema() -> None:
    registry = create_default_tool_registry()

    tools = tool_definitions_for_claude(registry)
    finish_task = next(tool for tool in tools if tool["name"] == "finish_task")

    assert "description" in finish_task
    assert finish_task["input_schema"]["type"] == "object"
    assert "status" in finish_task["input_schema"]["properties"]


def test_tool_result_block_serializes_structured_result() -> None:
    result = ToolResult.failure(
        tool_name="click_element",
        message="Failed to click element",
        error_code="click_failed",
        data={"selector": "#missing"},
    )

    block = tool_result_block("toolu_test", result)

    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "toolu_test"
    assert block["is_error"] is True
    assert json.loads(block["content"])["error_code"] == "click_failed"
