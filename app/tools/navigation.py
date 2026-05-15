from __future__ import annotations

from pydantic import BaseModel

from app.tools.registry import ToolContext
from app.tools.schemas import NavigateToUrlInput, ToolResult


async def navigate_to_url(input_data: BaseModel, context: ToolContext) -> ToolResult:
    args = NavigateToUrlInput.model_validate(input_data)
    try:
        page = await context.browser.get_active_page()
        response = await page.goto(args.url, wait_until="domcontentloaded")
        title = await page.title()
        return ToolResult.success(
            tool_name="navigate_to_url",
            message="Navigation completed",
            data={
                "url": page.url,
                "title": title,
                "status": response.status if response is not None else None,
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
