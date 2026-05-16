from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel

from app.browser.dom_extractor import DOMExtractor
from app.subagents.dom_agent import DOMSubAgent
from app.tools.registry import ToolContext
from app.tools.schemas import DomCandidate, QueryDomInput, ToolResult


async def query_dom(input_data: BaseModel, context: ToolContext) -> ToolResult:
    args = QueryDomInput.model_validate(input_data)
    try:
        page = await context.browser.get_active_page()
        extractor = DOMExtractor(context.browser.settings)
        candidates = await extractor.extract(page, query=args.query)

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
                    "candidate_preview": [],
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
                "candidate_preview": _candidate_preview(candidates),
                "active_layer_selector": _first_non_empty(
                    candidate.active_layer_selector for candidate in candidates
                ),
                "active_work_area_selector": _first_non_empty(
                    candidate.active_work_area_selector for candidate in candidates
                ),
                "diagnostic_hint": (
                    "Use candidate_preview to recover when matches are missing or low-confidence. "
                    "Prefer candidates inside active_layer_selector or active_work_area_selector."
                ),
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


def _candidate_preview(
    candidates: list[DomCandidate],
    *,
    limit: int = 8,
) -> list[dict[str, object]]:
    preview = []
    for candidate in candidates[:limit]:
        preview.append(
            {
                "selector": candidate.selector,
                "text": candidate.text,
                "aria_label": candidate.aria_label,
                "placeholder": candidate.placeholder,
                "role": candidate.role,
                "tag": candidate.tag,
                "is_clickable": candidate.is_clickable,
                "is_editable": candidate.is_editable,
                "query_match_score": candidate.query_match_score,
                "selector_stability": candidate.selector_stability,
                "center_occluded": candidate.center_occluded,
                "rect": candidate.rect,
                "active_layer_selector": candidate.active_layer_selector,
                "active_work_area_selector": candidate.active_work_area_selector,
            }
        )
    return preview


def _first_non_empty(values: Iterable[str | None]) -> str | None:
    for value in values:
        if value:
            return str(value)
    return None
