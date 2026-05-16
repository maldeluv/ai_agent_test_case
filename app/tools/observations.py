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

        tabs = []
        tabs_error = None
        list_pages = getattr(context.browser, "list_pages", None)
        if list_pages is not None:
            try:
                tabs = await list_pages()
            except Exception as exc:
                tabs = []
                tabs_error = f"{type(exc).__name__}: {exc}"
        active_tab_index = next(
            (tab["index"] for tab in tabs if tab.get("active") is True),
            None,
        )

        return ToolResult.success(
            tool_name="get_current_page_info",
            message="Current page info collected",
            data={
                "url": page.url,
                "title": title,
                "active_tab_index": active_tab_index,
                "tabs": tabs,
                "tabs_error": tabs_error,
                "short_visible_text": truncate_text(
                    visible_text,
                    max_chars=context.browser.settings.short_visible_text_chars,
                ),
                "hint": (
                    "If this visible text does not match the expected page, call list_tabs "
                    "and switch_tab before deciding the content is missing."
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
