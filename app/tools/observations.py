from __future__ import annotations

from pydantic import BaseModel

from app.tools.registry import ToolContext
from app.tools.schemas import EmptyInput, ToolResult
from app.utils.truncate import truncate_text


async def get_current_page_info(input_data: BaseModel, context: ToolContext) -> ToolResult:
    EmptyInput.model_validate(input_data)
    try:
        page = await context.browser.get_active_page()
        title = await page.title()
        visible_text = ""

        try:
            visible_text = await page.locator("body").inner_text(timeout=1500)
        except Exception:
            visible_text = ""

        return ToolResult.success(
            tool_name="get_current_page_info",
            message="Current page info collected",
            data={
                "url": page.url,
                "title": title,
                "short_visible_text": truncate_text(
                    visible_text,
                    max_chars=context.browser.settings.short_visible_text_chars,
                ),
            },
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="get_current_page_info",
            message=f"Failed to collect current page info: {exc}",
            error_code="page_info_failed",
            data={"exception_type": type(exc).__name__},
            next_hint="Ensure the browser session is started.",
        )
