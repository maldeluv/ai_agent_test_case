from __future__ import annotations

from pydantic import BaseModel

from app.tools.registry import ToolContext
from app.tools.schemas import (
    ClickElementInput,
    ScrollPageInput,
    ToolResult,
    TypeTextInput,
)


async def click_element(input_data: BaseModel, context: ToolContext) -> ToolResult:
    args = ClickElementInput.model_validate(input_data)
    try:
        page = await context.browser.get_active_page()
        await page.locator(args.selector).click(timeout=5000)
        return ToolResult.success(
            tool_name="click_element",
            message="Clicked element successfully",
            data={
                "selector": args.selector,
                "action_description": args.action_description,
            },
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="click_element",
            message=f"Failed to click element: {exc}",
            error_code="click_failed",
            data={
                "selector": args.selector,
                "exception_type": type(exc).__name__,
            },
            next_hint=(
                "Refresh page info or call query_dom for a fresh selector before retrying. "
                "Do not repeat the same failed click indefinitely."
            ),
        )


async def type_text(input_data: BaseModel, context: ToolContext) -> ToolResult:
    args = TypeTextInput.model_validate(input_data)
    try:
        page = await context.browser.get_active_page()
        locator = page.locator(args.selector)
        await locator.fill(args.text, timeout=5000)
        if args.press_enter:
            await locator.press("Enter", timeout=5000)
        return ToolResult.success(
            tool_name="type_text",
            message="Typed text successfully",
            data={
                "selector": args.selector,
                "press_enter": args.press_enter,
                "action_description": args.action_description,
            },
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="type_text",
            message=f"Failed to type text: {exc}",
            error_code="type_failed",
            data={
                "selector": args.selector,
                "exception_type": type(exc).__name__,
            },
            next_hint=(
                "Call query_dom for a fresh editable selector and check whether the target "
                "accepts text before retrying."
            ),
        )


async def scroll_page(input_data: BaseModel, context: ToolContext) -> ToolResult:
    args = ScrollPageInput.model_validate(input_data)
    try:
        page = await context.browser.get_active_page()
        delta_y = args.amount if args.direction == "down" else -args.amount
        await page.mouse.wheel(0, delta_y)
        return ToolResult.success(
            tool_name="scroll_page",
            message="Scrolled page successfully",
            data={
                "direction": args.direction,
                "amount": args.amount,
            },
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="scroll_page",
            message=f"Failed to scroll page: {exc}",
            error_code="scroll_failed",
            data={"exception_type": type(exc).__name__},
            next_hint="Ensure the active page is available before retrying.",
        )
