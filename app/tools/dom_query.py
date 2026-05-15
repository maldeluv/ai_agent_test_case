from __future__ import annotations

from pydantic import BaseModel

from app.browser.dom_extractor import DOMExtractor
from app.subagents.dom_agent import DOMSubAgent
from app.tools.registry import ToolContext
from app.tools.schemas import QueryDomInput, ToolResult


async def query_dom(input_data: BaseModel, context: ToolContext) -> ToolResult:
    args = QueryDomInput.model_validate(input_data)
    try:
        page = await context.browser.get_active_page()
        extractor = DOMExtractor(context.browser.settings)
        candidates = await extractor.extract(page)

        if not candidates:
            return ToolResult.success(
                tool_name="query_dom",
                message="DOM query completed with no candidates",
                data={
                    "query": args.query,
                    "found": False,
                    "answer": "No visible interactive DOM candidates were found.",
                    "matches": [],
                    "candidate_count": 0,
                },
            )

        dom_agent = DOMSubAgent(context.browser.settings)
        result = await dom_agent.analyze(query=args.query, candidates=candidates)
        return ToolResult.success(
            tool_name="query_dom",
            message="DOM query completed",
            data={
                "query": args.query,
                "found": result.found,
                "answer": result.answer,
                "matches": [
                    match.model_dump(mode="json")
                    for match in result.matches
                ],
                "candidate_count": len(candidates),
            },
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="query_dom",
            message=f"Failed to query DOM: {exc}",
            error_code="query_dom_failed",
            data={"query": args.query, "exception_type": type(exc).__name__},
            next_hint="Use get_current_page_info, wait, or try query_dom again after the page changes.",
        )
