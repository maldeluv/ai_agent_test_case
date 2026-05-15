from __future__ import annotations

from pydantic import BaseModel

from app.browser.actionability import stabilize_page
from app.tools.registry import ToolContext
from app.tools.schemas import EmptyInput, NavigateToUrlInput, ToolResult


async def navigate_to_url(input_data: BaseModel, context: ToolContext) -> ToolResult:
    args = NavigateToUrlInput.model_validate(input_data)
    try:
        page = await context.browser.get_active_page()
        response = await page.goto(args.url, wait_until="domcontentloaded")
        stabilization = await stabilize_page(page, context)
        title = await page.title()
        return ToolResult.success(
            tool_name="navigate_to_url",
            message="Navigation completed",
            data={
                "url": page.url,
                "title": title,
                "status": response.status if response is not None else None,
                "stabilization": stabilization,
            },
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="navigate_to_url",
            message=f"Failed to navigate to URL: {exc}",
            error_code="navigation_failed",
            data={"url": args.url, "exception_type": type(exc).__name__},
            next_hint=(
                "Check the URL and current browser state with get_current_page_info, "
                "then retry only if navigation is still needed."
            ),
        )


async def go_back(input_data: BaseModel, context: ToolContext) -> ToolResult:
    EmptyInput.model_validate(input_data)
    try:
        page = await context.browser.get_active_page()
        response = await page.go_back(wait_until="domcontentloaded")
        stabilization = await stabilize_page(page, context)
        title = await page.title()
        return ToolResult.success(
            tool_name="go_back",
            message="Browser history navigation completed",
            data={
                "url": page.url,
                "title": title,
                "status": response.status if response is not None else None,
                "had_history_entry": response is not None,
                "stabilization": stabilization,
            },
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="go_back",
            message=f"Failed to go back: {exc}",
            error_code="go_back_failed",
            data={"exception_type": type(exc).__name__},
            next_hint=(
                "Check current page state with get_current_page_info. If browser history "
                "is unavailable, navigate explicitly or use visible page controls."
            ),
        )
