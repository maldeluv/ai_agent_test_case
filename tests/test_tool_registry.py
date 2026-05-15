from __future__ import annotations

from pydantic import BaseModel
import pytest

from app.tools.registry import (
    ToolContext,
    ToolRegistry,
    create_default_tool_registry,
)
from app.tools.schemas import EmptyInput, ToolResult


class FakeBrowser:
    async def get_active_page(self) -> None:
        raise RuntimeError("browser is not started")


@pytest.mark.asyncio
async def test_default_registry_contains_base_tools() -> None:
    registry = create_default_tool_registry()

    assert {tool.name for tool in registry.list_tools()} == {
        "navigate_to_url",
        "go_back",
        "get_current_page_info",
        "wait",
        "take_screenshot",
        "ask_user_confirmation",
        "click_element",
        "type_text",
        "scroll_page",
        "scroll_element",
        "query_dom",
        "extract_visible_items",
        "finish_task",
    }


@pytest.mark.asyncio
async def test_unknown_tool_returns_structured_failure() -> None:
    registry = create_default_tool_registry()

    result = await registry.execute(
        "missing_tool",
        {},
        ToolContext(browser=FakeBrowser()),  # type: ignore[arg-type]
    )

    assert result.ok is False
    assert result.error_code == "unknown_tool"


@pytest.mark.asyncio
async def test_validation_error_returns_structured_failure() -> None:
    registry = create_default_tool_registry()

    result = await registry.execute(
        "navigate_to_url",
        {"url": "example.com"},
        ToolContext(browser=FakeBrowser()),  # type: ignore[arg-type]
    )

    assert result.ok is False
    assert result.error_code == "validation_error"
    assert result.data["errors"][0]["loc"] == ("url",)


@pytest.mark.asyncio
async def test_handler_exception_is_wrapped() -> None:
    async def broken_handler(_: BaseModel, __: ToolContext) -> ToolResult:
        raise RuntimeError("unexpected failure")

    registry = ToolRegistry()
    registry.register(
        name="broken",
        description="Broken test tool.",
        input_model=EmptyInput,
        handler=broken_handler,
    )

    result = await registry.execute(
        "broken",
        {},
        ToolContext(browser=FakeBrowser()),  # type: ignore[arg-type]
    )

    assert result.ok is False
    assert result.error_code == "tool_exception"
    assert result.data["exception_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_finish_task_returns_structured_success() -> None:
    registry = create_default_tool_registry()

    result = await registry.execute(
        "finish_task",
        {"status": "success", "summary": "Done"},
        ToolContext(browser=FakeBrowser()),  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert result.data == {"status": "success", "summary": "Done"}
