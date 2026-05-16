from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.browser.actionability import (
    click_diagnostics,
    click_target,
    scroll_locator_into_view,
    stabilize_page,
    wait_locator_visible,
)
from app.tools.registry import ToolContext
from app.tools.schemas import (
    ClickElementInput,
    ScrollElementInput,
    ScrollPageInput,
    ToolResult,
    TypeTextInput,
)


async def click_element(input_data: BaseModel, context: ToolContext) -> ToolResult:
    args = ClickElementInput.model_validate(input_data)
    try:
        page = await context.browser.get_active_page()
        page_ids = getattr(context.browser, "page_ids", None)
        known_page_ids = page_ids() if page_ids is not None else None
        click_info = await click_target(args, page, context)
        timeout_ms = int(getattr(context.browser.settings, "browser_action_timeout_ms", 7000))
        wait_for_page_after_action = getattr(
            context.browser,
            "wait_for_page_after_action",
            None,
        )
        active_page = page
        if wait_for_page_after_action is not None:
            new_tab_timeout_ms = int(
                getattr(
                    context.browser.settings,
                    "browser_new_tab_timeout_ms",
                    min(timeout_ms, 4000),
                )
            )
            active_page = await wait_for_page_after_action(
                previous_page=page,
                known_page_ids=known_page_ids,
                timeout_ms=new_tab_timeout_ms,
            )
        stabilization = await stabilize_page(active_page, context)
        return ToolResult.success(
            tool_name="click_element",
            message="Clicked element successfully",
            data={
                "selector": args.selector,
                "action_description": args.action_description,
                "position": args.position,
                "strategy": args.strategy,
                "method": click_info["method"],
                "clicked_selector": click_info.get("clicked_selector", args.selector),
                "active_url": getattr(active_page, "url", ""),
                "opened_or_switched_tab": active_page is not page,
                "stabilization": stabilization,
            },
        )
    except Exception as exc:
        try:
            page = await context.browser.get_active_page()
            diagnostics = await click_diagnostics(
                page,
                selector=args.selector,
                position=args.position,
            )
        except Exception as diagnostic_exc:
            diagnostics = {"diagnostics_error": str(diagnostic_exc)}

        return ToolResult.failure(
            tool_name="click_element",
            message=f"Failed to click element: {exc}",
            error_code="click_failed",
            data={
                "selector": args.selector,
                "position": args.position,
                "strategy": args.strategy,
                "exception_type": type(exc).__name__,
                "click_diagnostics": diagnostics,
            },
            next_hint=(
                "Inspect click_diagnostics.element_from_point. If another element "
                "intercepts the click, close/scroll past that overlay, refresh selectors "
                "with query_dom or extract_visible_items, or retry with another position "
                "such as left/right/top/bottom. Use strategy='coordinates' only when the "
                "diagnostic point clearly belongs to the intended visible row."
            ),
        )


async def type_text(input_data: BaseModel, context: ToolContext) -> ToolResult:
    args = TypeTextInput.model_validate(input_data)
    try:
        page = await context.browser.get_active_page()
        timeout_ms = int(getattr(context.browser.settings, "browser_action_timeout_ms", 7000))
        locator = page.locator(args.selector)
        await wait_locator_visible(locator, timeout_ms)
        await scroll_locator_into_view(locator, timeout_ms)
        method = "fill"
        try:
            await locator.fill(args.text, timeout=timeout_ms)
        except Exception:
            method = "keyboard"
            await locator.click(timeout=timeout_ms)
            await page.keyboard.type(args.text, delay=20)

        verification_supported, text_observed_before_enter = await _read_editable_text(locator)
        if (
            verification_supported
            and args.text not in text_observed_before_enter
        ):
            return ToolResult.failure(
                tool_name="type_text",
                message="Typed text was not observed in the editable target.",
                error_code="type_failed",
                data={
                    "selector": args.selector,
                    "press_enter": args.press_enter,
                    "enter_pressed": False,
                    "text_observed_before_enter": text_observed_before_enter,
                    "text_remaining_after_enter": None,
                    "method": method,
                    "verification": {
                        "status": "text_not_observed",
                        "expected_text_length": len(args.text),
                    },
                },
                next_hint=(
                    "The target did not retain the typed text. Call query_dom for a "
                    "fresh editable selector or use a different editor target before retrying."
                ),
            )

        if args.press_enter:
            if method == "fill":
                await locator.press("Enter", timeout=timeout_ms)
            else:
                await page.keyboard.press("Enter")
        stabilization = await stabilize_page(page, context)
        _, text_remaining_after_enter = (
            await _read_editable_text(locator)
            if args.press_enter
            else (verification_supported, text_observed_before_enter)
        )
        verification_status = (
            "submitted_attempted_requires_observation"
            if args.press_enter
            else (
                "text_observed"
                if verification_supported
                else "verification_unavailable"
            )
        )
        return ToolResult.success(
            tool_name="type_text",
            message=(
                "Typed text and pressed Enter; submission/send attempted"
                if args.press_enter
                else "Typed text successfully"
            ),
            data={
                "selector": args.selector,
                "press_enter": args.press_enter,
                "enter_pressed": args.press_enter,
                "action_description": args.action_description,
                "method": method,
                "text_observed_before_enter": text_observed_before_enter,
                "text_remaining_after_enter": text_remaining_after_enter,
                "verification": {
                    "status": verification_status,
                    "text_verified_in_target": (
                        args.text in text_observed_before_enter
                        if verification_supported
                        else None
                    ),
                    "requires_follow_up_observation": args.press_enter,
                },
                "stabilization": stabilization,
            },
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="type_text",
            message=f"Failed to type text: {exc}",
            error_code="type_failed",
            data={
                "selector": args.selector,
                "exception_type": type(exc).__name__,
            },
            next_hint=(
                "Call query_dom for a fresh editable selector and check whether the target "
                "accepts text before retrying."
            ),
        )


async def _read_editable_text(locator: Any) -> tuple[bool, str]:
    evaluate = getattr(locator, "evaluate", None)
    if evaluate is None:
        return False, ""
    try:
        value = await evaluate(
            """
            (element) => {
              const tag = element.tagName ? element.tagName.toLowerCase() : "";
              if (tag === "input" || tag === "textarea") {
                return element.value || "";
              }
              if (element.isContentEditable || element.getAttribute("role") === "textbox") {
                return element.innerText || element.textContent || "";
              }
              return element.textContent || "";
            }
            """
        )
    except Exception:
        return False, ""
    return True, str(value or "")


async def scroll_page(input_data: BaseModel, context: ToolContext) -> ToolResult:
    args = ScrollPageInput.model_validate(input_data)
    try:
        page = await context.browser.get_active_page()
        delta_y = args.amount if args.direction == "down" else -args.amount
        await page.mouse.wheel(0, delta_y)
        stabilization = await stabilize_page(page, context)
        return ToolResult.success(
            tool_name="scroll_page",
            message="Scrolled page successfully",
            data={
                "direction": args.direction,
                "amount": args.amount,
                "stabilization": stabilization,
            },
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="scroll_page",
            message=f"Failed to scroll page: {exc}",
            error_code="scroll_failed",
            data={"exception_type": type(exc).__name__},
            next_hint="Ensure the active page is available before retrying.",
        )


async def scroll_element(input_data: BaseModel, context: ToolContext) -> ToolResult:
    args = ScrollElementInput.model_validate(input_data)
    try:
        page = await context.browser.get_active_page()
        timeout_ms = int(getattr(context.browser.settings, "browser_action_timeout_ms", 7000))
        locator = page.locator(args.selector)
        await wait_locator_visible(locator, timeout_ms)
        delta_y = args.amount if args.direction == "down" else -args.amount
        scroll_state = await locator.evaluate(
            """
            (element, deltaY) => {
              const before = {
                scrollTop: element.scrollTop || 0,
                scrollLeft: element.scrollLeft || 0,
              };
              const scrollable =
                element.scrollHeight > element.clientHeight ||
                element.scrollWidth > element.clientWidth;
              element.scrollBy({ top: deltaY, left: 0, behavior: "instant" });
              return {
                scrollable,
                before,
                after: {
                  scrollTop: element.scrollTop || 0,
                  scrollLeft: element.scrollLeft || 0,
                },
                scrollHeight: element.scrollHeight || 0,
                clientHeight: element.clientHeight || 0,
              };
            }
            """,
            delta_y,
        )
        stabilization = await stabilize_page(page, context)
        return ToolResult.success(
            tool_name="scroll_element",
            message="Element scrolled successfully",
            data={
                "selector": args.selector,
                "direction": args.direction,
                "amount": args.amount,
                "scroll_state": scroll_state,
                "stabilization": stabilization,
            },
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="scroll_element",
            message=f"Failed to scroll element: {exc}",
            error_code="scroll_element_failed",
            data={
                "selector": args.selector,
                "exception_type": type(exc).__name__,
            },
            next_hint=(
                "Use query_dom or extract_visible_items to find the current list or "
                "scroll container, then retry with a fresh selector."
            ),
        )
