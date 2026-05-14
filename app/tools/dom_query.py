from __future__ import annotations

from pydantic import BaseModel

from app.tools.registry import ToolContext
from app.tools.schemas import QueryDomInput, ToolResult


async def query_dom(input_data: BaseModel, _: ToolContext) -> ToolResult:
    args = QueryDomInput.model_validate(input_data)
    return ToolResult.failure(
        tool_name="query_dom",
        message="query_dom is not implemented in this stage",
        error_code="query_dom_not_implemented",
        data={"query": args.query, "found": False, "matches": []},
        next_hint=(
            "Use get_current_page_info for coarse page observation. "
            "DOM extraction and DOM Sub-Agent will be added in the next stage."
        ),
    )
