from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from app.browser.session import BrowserSession
from app.tools.schemas import ToolResult

if TYPE_CHECKING:
    from app.safety import SafetyGuard


@dataclass
class ToolContext:
    browser: BrowserSession
    safety_guard: SafetyGuard | None = None
    user_task: str = ""


ToolHandler = Callable[[BaseModel, ToolContext], Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        input_model: type[BaseModel],
        handler: ToolHandler,
    ) -> None:
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            input_model=input_model,
            handler=handler,
        )

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any] | None,
        context: ToolContext,
    ) -> ToolResult:
        definition = self.get(name)
        if definition is None:
            return ToolResult.failure(
                tool_name=name,
                message=f"Unknown tool: {name}",
                error_code="unknown_tool",
                next_hint="Call one of the registered tools.",
            )

        try:
            validated = definition.input_model.model_validate(arguments or {})
        except ValidationError as exc:
            return ToolResult.failure(
                tool_name=name,
                message="Tool input validation failed",
                error_code="validation_error",
                data={"errors": exc.errors(include_context=False)},
                next_hint="Fix the tool arguments and retry.",
            )

        if context.safety_guard is not None:
            browser_context = await self._browser_context_for_safety(context)
            safety_result = context.safety_guard.check_tool_call(
                tool_name=name,
                arguments=validated.model_dump(mode="json", exclude_none=True),
                browser_context=browser_context,
            )
            if safety_result is not None:
                return safety_result
        else:
            browser_context = {}

        try:
            result = await definition.handler(validated, context)
            if context.safety_guard is not None and result.ok:
                self._record_tool_evidence(
                    name=name,
                    result=result,
                    context=context,
                    browser_context=browser_context,
                )
                context.safety_guard.consume_approval_for_tool_call(
                    tool_name=name,
                    arguments=validated.model_dump(mode="json", exclude_none=True),
                    browser_context=browser_context,
                )
            return result
        except Exception as exc:
            return ToolResult.failure(
                tool_name=name,
                message=str(exc),
                error_code="tool_exception",
                data={"exception_type": type(exc).__name__},
                next_hint="Inspect current page state before retrying.",
            )

    def _record_tool_evidence(
        self,
        *,
        name: str,
        result: ToolResult,
        context: ToolContext,
        browser_context: dict[str, Any],
    ) -> None:
        if context.safety_guard is None:
            return
        if name not in {
            "extract_visible_items",
            "classify_items_with_evidence",
            "prepare_batch_action_confirmation",
        }:
            return
        raw_items = result.data.get("items")
        if not isinstance(raw_items, list):
            return
        context.safety_guard.record_classified_items(
            items=[item for item in raw_items if isinstance(item, dict)],
            browser_context=browser_context,
        )

    async def _browser_context_for_safety(self, context: ToolContext) -> dict[str, Any]:
        page_context: dict[str, Any] = {}
        try:
            page = await context.browser.get_active_page()
            page_context["active_url"] = getattr(page, "url", "")
        except Exception as exc:
            page_context["active_page_error"] = f"{type(exc).__name__}: {exc}"
            return page_context

        list_pages = getattr(context.browser, "list_pages", None)
        if list_pages is not None:
            try:
                tabs = await list_pages()
                active_tab_index = next(
                    (tab["index"] for tab in tabs if tab.get("active") is True),
                    None,
                )
                page_context["active_tab_index"] = active_tab_index
            except Exception as exc:
                page_context["tabs_error"] = f"{type(exc).__name__}: {exc}"
        return page_context


def create_default_tool_registry() -> ToolRegistry:
    from app.tools.control import ask_user_confirmation, finish_task, take_screenshot, wait
    from app.tools.content import (
        classify_items_with_evidence,
        collect_visible_items,
        extract_visible_items,
        prepare_batch_action_confirmation,
    )
    from app.tools.dom_query import query_dom
    from app.tools.interactions import click_element, scroll_element, scroll_page, type_text
    from app.tools.navigation import go_back, navigate_to_url
    from app.tools.observations import (
        get_current_page_info,
        get_element_info,
        wait_for_page_state,
    )
    from app.tools.tabs import list_tabs, switch_tab
    from app.tools.vision import observe_screenshot
    from app.tools.schemas import (
        AskUserConfirmationInput,
        ClassifyItemsWithEvidenceInput,
        ClickElementInput,
        CollectVisibleItemsInput,
        EmptyInput,
        ExtractVisibleItemsInput,
        FinishTaskInput,
        GetElementInfoInput,
        NavigateToUrlInput,
        ObserveScreenshotInput,
        PrepareBatchActionConfirmationInput,
        QueryDomInput,
        ScrollElementInput,
        ScrollPageInput,
        SwitchTabInput,
        TakeScreenshotInput,
        TypeTextInput,
        WaitInput,
        WaitForPageStateInput,
    )

    registry = ToolRegistry()
    registry.register(
        name="navigate_to_url",
        description="Navigate the active browser page to an http(s) URL.",
        input_model=NavigateToUrlInput,
        handler=navigate_to_url,
    )
    registry.register(
        name="go_back",
        description=(
            "Go back one entry in browser history. Useful after opening an item "
            "from a list to inspect details and return to the list."
        ),
        input_model=EmptyInput,
        handler=go_back,
    )
    registry.register(
        name="get_current_page_info",
        description=(
            "Collect URL, title, compact visible text, and browser tab summary "
            "from the active page. Includes untrusted_content_warnings when visible "
            "page text looks like prompt-injection content."
        ),
        input_model=EmptyInput,
        handler=get_current_page_info,
    )
    registry.register(
        name="list_tabs",
        description=(
            "List open browser tabs with index, URL, title, and active flag. "
            "Use this when a click or website may have opened a new tab."
        ),
        input_model=EmptyInput,
        handler=list_tabs,
    )
    registry.register(
        name="switch_tab",
        description=(
            "Switch the active browser page to a tab index returned by list_tabs "
            "or get_current_page_info."
        ),
        input_model=SwitchTabInput,
        handler=switch_tab,
    )
    registry.register(
        name="wait",
        description="Wait for a short number of seconds on the active page.",
        input_model=WaitInput,
        handler=wait,
    )
    registry.register(
        name="wait_for_page_state",
        description=(
            "Wait until a selector, visible text fragment, or URL fragment is observed. "
            "Prefer this over blind wait when expecting search results, cart counters, "
            "modals, form validation, navigation, or other concrete UI changes."
        ),
        input_model=WaitForPageStateInput,
        handler=wait_for_page_state,
    )
    registry.register(
        name="take_screenshot",
        description="Save a screenshot of the active page to screenshots/.",
        input_model=TakeScreenshotInput,
        handler=take_screenshot,
    )
    registry.register(
        name="observe_screenshot",
        description=(
            "Fallback visual observation of the current browser screenshot. Use only "
            "when DOM/text tools are insufficient or contradictory, such as canvas UI, "
            "unclear overlays, visual layout ambiguity, or repeated selector failures. "
            "Returns visual regions and a suggested next step, but never exact CSS selectors."
        ),
        input_model=ObserveScreenshotInput,
        handler=observe_screenshot,
    )
    registry.register(
        name="ask_user_confirmation",
        description=(
            "Ask the user for explicit confirmation before a risky external action. "
            "Use this for payments, final order confirmation, deleting emails, "
            "marking spam, sending applications/messages, or submitting forms. "
            "When a previous tool result returned safety_confirmation_required, pass "
            "its approval_id if present."
        ),
        input_model=AskUserConfirmationInput,
        handler=ask_user_confirmation,
    )
    registry.register(
        name="click_element",
        description=(
            "Click an element found by a CSS selector. Include action_description "
            "when the click may pay, submit, delete, send, mark spam, or confirm an order. "
            "If a normal click is intercepted, retry with position='left'/'right'/'top'/'bottom' "
            "or strategy='nearest_clickable_ancestor' after inspecting click_diagnostics."
        ),
        input_model=ClickElementInput,
        handler=click_element,
    )
    registry.register(
        name="type_text",
        description=(
            "Fill text into an editable element and optionally press Enter. Include "
            "action_description when Enter may submit a form, send a message, or create an external effect."
        ),
        input_model=TypeTextInput,
        handler=type_text,
    )
    registry.register(
        name="scroll_page",
        description="Scroll the active page up or down by a pixel amount.",
        input_model=ScrollPageInput,
        handler=scroll_page,
    )
    registry.register(
        name="scroll_element",
        description=(
            "Scroll a specific visible scroll container by selector. Use this for "
            "mail inboxes, tables, chat panes, feeds, and other inner scrolling lists."
        ),
        input_model=ScrollElementInput,
        handler=scroll_element,
    )
    registry.register(
        name="query_dom",
        description=(
            "Find relevant visible interactive elements on the active page. "
            "Returns found, answer, matches with selectors, and confidence. "
            "Also includes a compact candidate_preview and active layer/work-area diagnostics. "
            "Use this before click_element or type_text instead of guessing selectors."
        ),
        input_model=QueryDomInput,
        handler=query_dom,
    )
    registry.register(
        name="get_element_info",
        description=(
            "Read the current state of a known selector: text/value, labels, role, "
            "visibility, checked/disabled state, rect, and occlusion diagnostics. "
            "Use this to verify counters, selected quantities, modal controls, "
            "or typed values after an action."
        ),
        input_model=GetElementInfoInput,
        handler=get_element_info,
    )
    registry.register(
        name="extract_visible_items",
        description=(
            "Extract and semantically analyze visible repeated content items such as "
            "email rows, table rows, product cards, search results, notifications, "
            "or list entries. Use this when the task says read, summarize, classify, "
            "compare, or process items in a visible list. It returns item selectors, "
            "fields, classifications, confidence, and nearby controls."
        ),
        input_model=ExtractVisibleItemsInput,
        handler=extract_visible_items,
    )
    registry.register(
        name="collect_visible_items",
        description=(
            "Collect unique visible repeated items across the current viewport and "
            "scroll steps. Use this for mail inboxes, virtualized lists, tables, "
            "feeds, and search results when a task asks for N visible items. Returns "
            "source_text, selectors, controls, scroll container, and availability count."
        ),
        input_model=CollectVisibleItemsInput,
        handler=collect_visible_items,
    )
    registry.register(
        name="classify_items_with_evidence",
        description=(
            "Classify or analyze a provided list of visible items using only their "
            "source_text and controls. Use after collect_visible_items before risky "
            "batch actions such as deleting or marking spam."
        ),
        input_model=ClassifyItemsWithEvidenceInput,
        handler=classify_items_with_evidence,
    )
    registry.register(
        name="prepare_batch_action_confirmation",
        description=(
            "Prepare exact ask_user_confirmation and click_element arguments for "
            "a risky batch action from classified visible item evidence. Use after "
            "classify_items_with_evidence and before deleting or marking spam."
        ),
        input_model=PrepareBatchActionConfirmationInput,
        handler=prepare_batch_action_confirmation,
    )
    registry.register(
        name="finish_task",
        description=(
            "Finish the current task with a status and concise summary. "
            "Use this when the objective is complete, blocked, failed, or needs user input."
        ),
        input_model=FinishTaskInput,
        handler=finish_task,
    )
    return registry
