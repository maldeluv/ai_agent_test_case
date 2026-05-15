from __future__ import annotations

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
        click_info = await click_target(args, page, context)
        stabilization = await stabilize_page(page, context)
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

        if args.press_enter:
            if method == "fill":
                await locator.press("Enter", timeout=timeout_ms)
            else:
                await page.keyboard.press("Enter")
        stabilization = await stabilize_page(page, context)
        return ToolResult.success(
            tool_name="type_text",
            message="Typed text successfully",
            data={
                "selector": args.selector,
                "press_enter": args.press_enter,
                "action_description": args.action_description,
                "method": method,
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
