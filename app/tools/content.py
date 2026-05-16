from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel

from app.browser.content_extractor import ContentExtractor
from app.safety.prompt_injection import detect_prompt_injection_warnings
from app.subagents.content_agent import ContentSubAgent
from app.tools.registry import ToolContext
from app.tools.schemas import (
    ClassifyItemsWithEvidenceInput,
    CollectVisibleItemsInput,
    ContentItemAnalysis,
    ExtractVisibleItemsInput,
    PrepareBatchActionConfirmationInput,
    ToolResult,
    VisibleItem,
    VisibleItemControl,
)


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
        untrusted_content_warnings = _warnings_for_visible_items(visible_items)
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
                "error_code": result.error_code,
                "raw_preview": result.raw_preview,
                "untrusted_content_warnings": untrusted_content_warnings,
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


async def collect_visible_items(input_data: BaseModel, context: ToolContext) -> ToolResult:
    args = CollectVisibleItemsInput.model_validate(input_data)
    try:
        page = await context.browser.get_active_page()
        extractor = ContentExtractor(context.browser.settings)
        collected: list[VisibleItem] = []
        seen_keys: set[str] = set()
        scroll_states: list[dict[str, object]] = []
        exhausted = False

        for step in range(args.max_scroll_steps + 1):
            visible_items = await extractor.extract(
                page,
                query=args.query,
                max_items=args.target_count,
            )
            added = _merge_visible_items(
                collected=collected,
                seen_keys=seen_keys,
                items=visible_items,
                target_count=args.target_count,
            )
            if len(collected) >= args.target_count:
                break
            if step >= args.max_scroll_steps:
                break

            scroll_selector = args.container_selector or _choose_scroll_container(
                visible_items or collected
            )
            scroll_state = await _scroll_for_more_items(
                page=page,
                selector=scroll_selector,
                amount=args.scroll_amount,
            )
            scroll_states.append(scroll_state)
            if not scroll_state.get("moved") and added == 0:
                exhausted = True
                break

        return ToolResult.success(
            tool_name="collect_visible_items",
            message="Visible item collection completed",
            data={
                "query": args.query,
                "target_count": args.target_count,
                "collected_count": len(collected),
                "reached_target": len(collected) >= args.target_count,
                "available_count": len(collected),
                "exhausted": exhausted or len(collected) < args.target_count,
                "scroll_steps": len(scroll_states),
                "scroll_states": scroll_states,
                "items": _visible_items_jsonable(collected),
                "untrusted_content_warnings": _warnings_for_visible_items(collected),
                "answer": (
                    f"Collected {len(collected)} visible item(s)."
                    if len(collected) >= args.target_count
                    else f"Only {len(collected)} visible item(s) were available before the scroll limit or list end."
                ),
            },
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="collect_visible_items",
            message=f"Failed to collect visible items: {exc}",
            error_code="collect_visible_items_failed",
            data={"query": args.query, "exception_type": type(exc).__name__},
            next_hint=(
                "Use get_current_page_info, wait, or query_dom to find the list "
                "container, then retry with container_selector if needed."
            ),
        )


async def classify_items_with_evidence(
    input_data: BaseModel,
    context: ToolContext,
) -> ToolResult:
    args = ClassifyItemsWithEvidenceInput.model_validate(input_data)
    try:
        content_agent = ContentSubAgent(context.browser.settings)
        result = await content_agent.analyze(query=args.query, items=args.items)
        result = _apply_deterministic_email_fallback(result)
        return ToolResult.success(
            tool_name="classify_items_with_evidence",
            message="Visible item evidence classification completed",
            data={
                "query": args.query,
                "found": result.found,
                "answer": result.answer,
                "items": [
                    item.model_dump(mode="json", exclude_none=True)
                    for item in result.items
                ],
                "error_code": result.error_code,
                "raw_preview": result.raw_preview,
                "untrusted_content_warnings": _warnings_for_visible_items(args.items),
            },
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="classify_items_with_evidence",
            message=f"Failed to classify visible items: {exc}",
            error_code="classify_items_failed",
            data={"query": args.query, "exception_type": type(exc).__name__},
            next_hint=(
                "Pass the exact items returned by collect_visible_items or "
                "extract_visible_items, without inventing fields."
            ),
        )


async def prepare_batch_action_confirmation(
    input_data: BaseModel,
    context: ToolContext,
) -> ToolResult:
    args = PrepareBatchActionConfirmationInput.model_validate(input_data)
    try:
        allowed_classifications = {
            classification.casefold()
            for classification in args.classification_filter
        }
        selected: list[ContentItemAnalysis] = []
        excluded: list[dict[str, object]] = []
        for item in args.items:
            classification = (item.classification or "unknown").casefold()
            if (
                classification in allowed_classifications
                and item.confidence >= args.min_confidence
            ):
                selected.append(item)
            else:
                excluded.append(
                    {
                        "index": item.index,
                        "selector": item.selector,
                        "classification": item.classification,
                        "confidence": item.confidence,
                    }
                )

        if not selected:
            return ToolResult.failure(
                tool_name="prepare_batch_action_confirmation",
                message="No classified visible items met the requested batch criteria.",
                error_code="no_batch_items_selected",
                data={
                    "action": args.action,
                    "classification_filter": args.classification_filter,
                    "min_confidence": args.min_confidence,
                    "excluded_items": excluded[:20],
                },
                next_hint=(
                    "Use classify_items_with_evidence first, lower min_confidence only "
                    "if the visible evidence justifies it, or finish_task if no matching "
                    "items are available."
                ),
            )

        batch_items = [_batch_item_from_analysis(item) for item in selected]
        label = "Delete" if args.action == "delete" else "Mark as spam"
        item_summaries = [_item_summary(item) for item in selected]
        target_context = (
            f"{label} {len(selected)} selected classified item(s): "
            + "; ".join(item_summaries[:8])
        )
        if len(item_summaries) > 8:
            target_context += f"; +{len(item_summaries) - 8} more"
        action_description = (
            f"{label} {len(selected)} selected spam/suspicious email or list item(s): "
            + "; ".join(item_summaries[:8])
        )
        if len(item_summaries) > 8:
            action_description += f"; +{len(item_summaries) - 8} more"
        reason = args.reason or (
            "This is a destructive or externally visible batch action over classified visible items."
        )

        data = {
            "action": args.action,
            "action_selector": args.action_selector,
            "reason": reason,
            "action_description": action_description,
            "target_context": target_context,
            "batch_items": batch_items,
            "included_count": len(selected),
            "excluded_count": len(excluded),
            "excluded_items": excluded[:20],
            "items": [
                item.model_dump(mode="json", exclude_none=True)
                for item in selected
            ],
            "click_element_args": {
                "selector": args.action_selector,
                "action_description": action_description,
                "target_context": target_context,
                "batch_items": batch_items,
            },
            "ask_user_confirmation_args": {
                "reason": reason,
                "action_description": action_description,
            },
        }
        return ToolResult.success(
            tool_name="prepare_batch_action_confirmation",
            message="Batch action confirmation payload prepared",
            data=data,
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="prepare_batch_action_confirmation",
            message=f"Failed to prepare batch confirmation payload: {exc}",
            error_code="prepare_batch_confirmation_failed",
            data={"exception_type": type(exc).__name__},
            next_hint=(
                "Pass classified items returned by classify_items_with_evidence and "
                "a concrete action_selector for the delete/spam control."
            ),
        )


def _merge_visible_items(
    *,
    collected: list[VisibleItem],
    seen_keys: set[str],
    items: list[VisibleItem],
    target_count: int,
) -> int:
    added = 0
    for item in items:
        key = _visible_item_key(item)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        collected.append(item.model_copy(update={"index": len(collected) + 1}))
        added += 1
        if len(collected) >= target_count:
            break
    return added


def _visible_item_key(item: VisibleItem) -> str:
    normalized_text = " ".join(item.text.casefold().split())
    if normalized_text:
        return f"text:{normalized_text}"
    return f"selector:{item.selector}"


def _choose_scroll_container(items: list[VisibleItem]) -> str | None:
    counts: dict[str, int] = {}
    for item in items:
        if item.scroll_container_selector:
            counts[item.scroll_container_selector] = (
                counts.get(item.scroll_container_selector, 0) + 1
            )
    if not counts:
        return None
    return max(counts.items(), key=lambda pair: pair[1])[0]


async def _scroll_for_more_items(
    *,
    page: object,
    selector: str | None,
    amount: int,
) -> dict[str, object]:
    if selector:
        locator = page.locator(selector)  # type: ignore[attr-defined]
        state = await locator.evaluate(
            """
            (element, deltaY) => {
              const before = element.scrollTop || 0;
              element.scrollBy({ top: deltaY, left: 0, behavior: "instant" });
              const after = element.scrollTop || 0;
              return {
                selector: null,
                scrollable: element.scrollHeight > element.clientHeight,
                before,
                after,
                moved: after !== before,
                scrollHeight: element.scrollHeight || 0,
                clientHeight: element.clientHeight || 0,
              };
            }
            """,
            amount,
        )
        if isinstance(state, dict):
            state["selector"] = selector
            return state
        return {"selector": selector, "moved": False, "raw_state": state}

    mouse = getattr(page, "mouse", None)
    if mouse is not None:
        await mouse.wheel(0, amount)
        return {"selector": None, "moved": True, "method": "page_mouse_wheel"}
    return {"selector": None, "moved": False, "method": "unavailable"}


def _visible_items_jsonable(items: list[VisibleItem]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for item in items:
        payload = item.model_dump(mode="json", exclude_none=True)
        payload["source_text"] = item.text
        result.append(payload)
    return result


def _warnings_for_visible_items(items: list[VisibleItem]) -> list[dict[str, str]]:
    text = "\n".join(
        item.source_text or item.text
        for item in items
        if item.source_text or item.text
    )
    return detect_prompt_injection_warnings(text)


def _apply_deterministic_email_fallback(result: object) -> object:
    items = getattr(result, "items", [])
    updated_items: list[ContentItemAnalysis] = []
    changed = False
    for item in items:
        local = _deterministic_email_classification(item)
        if (
            local is not None
            and ((item.classification or "unknown") == "unknown" or item.confidence < 0.45)
        ):
            classification, reason = local
            recommended_action = (
                "delete_or_mark_spam"
                if classification in {"spam", "suspicious"}
                else item.recommended_action
            )
            updated_items.append(
                item.model_copy(
                    update={
                        "classification": classification,
                        "reason": _append_reason(item.reason, reason),
                        "recommended_action": recommended_action,
                        "confidence": max(item.confidence, 0.6),
                    }
                )
            )
            changed = True
        else:
            updated_items.append(item)
    if changed and hasattr(result, "model_copy"):
        return result.model_copy(update={"items": updated_items})
    return result


def _deterministic_email_classification(
    item: ContentItemAnalysis,
) -> tuple[str, str] | None:
    text = " ".join(
        value
        for value in (
            item.source_text,
            item.summary,
            item.reason or "",
            " ".join(item.fields.values()),
        )
        if value
    ).casefold()
    spam_terms = (
        "unsubscribe",
        "limited offer",
        "huge sale",
        "discount",
        "promo",
        "promotion",
        "lottery",
        "winner",
        "casino",
        "free prize",
    )
    suspicious_terms = (
        "verify your account",
        "password expires",
        "urgent action",
        "click here",
        "suspended account",
        "security alert",
        "confirm your identity",
    )
    if any(term in text for term in spam_terms):
        return "spam", "Local visible-evidence fallback found promotional/spam terms."
    if any(term in text for term in suspicious_terms):
        return "suspicious", "Local visible-evidence fallback found suspicious account/action terms."
    return None


def _append_reason(existing: str | None, addition: str) -> str:
    if existing:
        return f"{existing} {addition}"
    return addition


def _batch_item_from_analysis(item: ContentItemAnalysis) -> dict[str, object]:
    fields = item.fields
    payload = {
        "selector": item.selector,
        "control_selector": _select_control_selector(item.controls),
        "evidence_signature": _evidence_signature(item),
        "item_index": item.index,
        "sender": fields.get("sender"),
        "subject": fields.get("subject"),
        "title": fields.get("title"),
        "snippet": fields.get("snippet"),
        "source_text": item.source_text,
    }
    return {key: value for key, value in payload.items() if value not in (None, "")}


def _select_control_selector(controls: list[VisibleItemControl]) -> str | None:
    enabled = [control for control in controls if not control.disabled]
    for control in enabled:
        if control.kind in {"checkbox", "radio"}:
            return control.selector
    return enabled[0].selector if enabled else None


def _evidence_signature(item: ContentItemAnalysis) -> str:
    payload = {
        "selector": item.selector,
        "index": item.index,
        "source_text": item.source_text,
        "fields": item.fields,
        "classification": item.classification,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def _item_summary(item: ContentItemAnalysis) -> str:
    fields = item.fields
    parts = [
        fields.get("sender") or fields.get("title"),
        fields.get("subject"),
        fields.get("snippet"),
    ]
    summary = " / ".join(part for part in parts if part)
    if summary:
        return summary[:180]
    return (item.summary or item.source_text or item.selector or f"item {item.index}")[:180]
