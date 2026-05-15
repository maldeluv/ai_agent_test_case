from __future__ import annotations

from pydantic import BaseModel

from app.browser.content_extractor import ContentExtractor
from app.subagents.content_agent import ContentSubAgent
from app.tools.registry import ToolContext
from app.tools.schemas import ExtractVisibleItemsInput, ToolResult


async def extract_visible_items(input_data: BaseModel, context: ToolContext) -> ToolResult:
    args = ExtractVisibleItemsInput.model_validate(input_data)
    try:
        page = await context.browser.get_active_page()
        extractor = ContentExtractor(context.browser.settings)
        visible_items = await extractor.extract(
            page,
            query=args.query,
            max_items=args.max_items,
        )

        if not visible_items:
            return ToolResult.success(
                tool_name="extract_visible_items",
                message="Visible item extraction completed with no items",
                data={
                    "query": args.query,
                    "found": False,
                    "answer": "No visible repeated content items were found.",
                    "items": [],
                    "raw_item_count": 0,
                },
            )

        content_agent = ContentSubAgent(context.browser.settings)
        result = await content_agent.analyze(query=args.query, items=visible_items)
        return ToolResult.success(
            tool_name="extract_visible_items",
            message="Visible item extraction completed",
            data={
                "query": args.query,
                "found": result.found,
                "answer": result.answer,
                "items": [
                    item.model_dump(mode="json", exclude_none=True)
                    for item in result.items
                ],
                "raw_item_count": len(visible_items),
            },
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="extract_visible_items",
            message=f"Failed to extract visible items: {exc}",
            error_code="extract_visible_items_failed",
            data={"query": args.query, "exception_type": type(exc).__name__},
            next_hint=(
                "Use wait, scroll_page, scroll_element, or get_current_page_info, "
                "then retry extract_visible_items with a more specific query."
            ),
        )
