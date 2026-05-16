from __future__ import annotations

from pydantic import BaseModel

from app.browser.actionability import stabilize_page
from app.tools.registry import ToolContext
from app.tools.schemas import EmptyInput, SwitchTabInput, ToolResult


async def list_tabs(input_data: BaseModel, context: ToolContext) -> ToolResult:
    EmptyInput.model_validate(input_data)
    try:
        list_pages = getattr(context.browser, "list_pages", None)
        if list_pages is None:
            return ToolResult.failure(
                tool_name="list_tabs",
                message="Browser session does not expose tab listing.",
                error_code="tabs_unavailable",
                next_hint="Use get_current_page_info to inspect the active page.",
            )

        tabs = await list_pages()
        active_tab_index = next(
            (tab["index"] for tab in tabs if tab.get("active") is True),
            None,
        )
        return ToolResult.success(
            tool_name="list_tabs",
            message="Browser tabs listed",
            data={
                "active_tab_index": active_tab_index,
                "tab_count": len(tabs),
                "tabs": tabs,
            },
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="list_tabs",
            message=f"Failed to list browser tabs: {exc}",
            error_code="list_tabs_failed",
            data={"exception_type": type(exc).__name__},
            next_hint="Use get_current_page_info to inspect the active page.",
        )


async def switch_tab(input_data: BaseModel, context: ToolContext) -> ToolResult:
    args = SwitchTabInput.model_validate(input_data)
    try:
        switch_to_page = getattr(context.browser, "switch_to_page", None)
        if switch_to_page is None:
            return ToolResult.failure(
                tool_name="switch_tab",
                message="Browser session does not expose tab switching.",
                error_code="tabs_unavailable",
                next_hint="Use get_current_page_info to inspect the active page.",
            )

        page = await switch_to_page(args.index)
        stabilization = await stabilize_page(page, context)
        title = await page.title()
        list_pages = getattr(context.browser, "list_pages", None)
        tabs = await list_pages() if list_pages is not None else []
        return ToolResult.success(
            tool_name="switch_tab",
            message="Switched active browser tab",
            data={
                "active_tab_index": args.index,
                "url": page.url,
                "title": title,
                "tabs": tabs,
                "stabilization": stabilization,
            },
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="switch_tab",
            message=f"Failed to switch browser tab: {exc}",
            error_code="switch_tab_failed",
            data={"index": args.index, "exception_type": type(exc).__name__},
            next_hint="Call list_tabs, choose an existing tab index, then retry switch_tab.",
        )
