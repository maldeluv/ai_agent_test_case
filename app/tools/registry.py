from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.browser.session import BrowserSession
from app.safety import SafetyGuard
from app.tools.schemas import ToolResult


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
            safety_result = context.safety_guard.check_tool_call(
                tool_name=name,
                arguments=validated.model_dump(mode="json", exclude_none=True),
            )
            if safety_result is not None:
                return safety_result

        try:
            return await definition.handler(validated, context)
        except Exception as exc:
            return ToolResult.failure(
                tool_name=name,
                message=str(exc),
                error_code="tool_exception",
                data={"exception_type": type(exc).__name__},
                next_hint="Inspect current page state before retrying.",
            )


def create_default_tool_registry() -> ToolRegistry:
    from app.tools.control import ask_user_confirmation, finish_task, take_screenshot, wait
    from app.tools.dom_query import query_dom
    from app.tools.interactions import click_element, scroll_page, type_text
    from app.tools.navigation import navigate_to_url
    from app.tools.observations import get_current_page_info
    from app.tools.schemas import (
        AskUserConfirmationInput,
        ClickElementInput,
        EmptyInput,
        FinishTaskInput,
        NavigateToUrlInput,
        QueryDomInput,
        ScrollPageInput,
        TakeScreenshotInput,
        TypeTextInput,
        WaitInput,
    )

    registry = ToolRegistry()
    registry.register(
        name="navigate_to_url",
        description="Navigate the active browser page to an http(s) URL.",
        input_model=NavigateToUrlInput,
        handler=navigate_to_url,
    )
    registry.register(
        name="get_current_page_info",
        description="Collect URL, title, and compact visible text from the active page.",
        input_model=EmptyInput,
        handler=get_current_page_info,
    )
    registry.register(
        name="wait",
        description="Wait for a short number of seconds on the active page.",
        input_model=WaitInput,
        handler=wait,
    )
    registry.register(
        name="take_screenshot",
        description="Save a screenshot of the active page to screenshots/.",
        input_model=TakeScreenshotInput,
        handler=take_screenshot,
    )
    registry.register(
        name="ask_user_confirmation",
        description=(
            "Ask the user for explicit confirmation before a risky external action. "
            "Use this for payments, final order confirmation, deleting emails, "
            "marking spam, sending applications/messages, or submitting forms."
        ),
        input_model=AskUserConfirmationInput,
        handler=ask_user_confirmation,
    )
    registry.register(
        name="click_element",
        description=(
            "Click an element found by a CSS selector. Include action_description "
            "when the click may pay, submit, delete, send, mark spam, or confirm an order."
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
        name="query_dom",
        description=(
            "Find relevant visible interactive elements on the active page. "
            "Returns found, answer, matches with selectors, and confidence. "
            "Use this before click_element or type_text instead of guessing selectors."
        ),
        input_model=QueryDomInput,
        handler=query_dom,
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
