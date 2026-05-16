from __future__ import annotations

from typing import Any, Protocol

from rich.console import Console
from rich.json import JSON
from rich.panel import Panel

from app.agent.prompts import MAIN_AGENT_SYSTEM_PROMPT
from app.agent.schemas import AgentRunResult
from app.agent.state import AgentState
from app.browser.session import BrowserSession
from app.config import Settings
from app.llm.client import create_llm_client
from app.llm.tool_use import (
    content_block_to_dict,
    get_block_text,
    get_block_type,
    get_tool_use_id,
    get_tool_use_input,
    get_tool_use_name,
    tool_definitions_for_provider,
    tool_result_block,
)
from app.safety import SafetyGuard
from app.tools.registry import ToolContext, ToolRegistry
from app.tools.schemas import ToolResult
from app.utils.logger import get_console, get_logger


class AgentModelClient(Protocol):
    async def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        pass


class MainAgentLoop:
    def __init__(
        self,
        *,
        settings: Settings,
        browser: BrowserSession,
        registry: ToolRegistry,
        client: AgentModelClient | None = None,
        safety_guard: SafetyGuard | None = None,
        console: Console | None = None,
    ) -> None:
        self.settings = settings
        self.browser = browser
        self.registry = registry
        self.client = client or create_llm_client(settings)
        self.safety_guard = safety_guard
        self.console = console or get_console()
        self._logger = get_logger(__name__)

    async def run(self, user_task: str) -> AgentRunResult:
        state = AgentState(user_task=user_task)
        previous_assistant_blocks: list[dict[str, Any]] | None = None
        previous_tool_result_blocks: list[dict[str, Any]] | None = None
        tools = tool_definitions_for_provider(
            self.registry,
            self.settings.llm_provider,
        )
        safety_guard = self.safety_guard or SafetyGuard(console=self.console)
        context = ToolContext(
            browser=self.browser,
            safety_guard=safety_guard,
            user_task=user_task,
        )
        consecutive_failures = 0

        for step in range(1, self.settings.max_steps + 1):
            self.console.rule(f"Agent Step {step}")
            messages = self._build_messages(
                state=state,
                previous_assistant_blocks=previous_assistant_blocks,
                previous_tool_result_blocks=previous_tool_result_blocks,
            )
            try:
                response = await self.client.create_message(
                    system=MAIN_AGENT_SYSTEM_PROMPT,
                    messages=messages,
                    tools=tools,
                )
            except Exception as exc:
                self._logger.error("LLM request failed: %s", exc)
                return AgentRunResult(
                    status="failed",
                    summary=f"LLM request failed: {exc}",
                    steps_used=step - 1,
                    debug_context=state.to_session_debug_context(self.settings),
                )

            assistant_blocks = [
                content_block_to_dict(block) for block in getattr(response, "content", [])
            ]

            tool_uses = []
            assistant_texts = []
            for block in getattr(response, "content", []):
                block_type = get_block_type(block)
                if block_type == "text":
                    text = get_block_text(block).strip()
                    if text:
                        assistant_texts.append(text)
                        self.console.print(f"[bold]Assistant:[/bold] {text}")
                elif block_type == "tool_use":
                    tool_uses.append(block)

            if not tool_uses:
                summary = "\n".join(assistant_texts).strip()
                return AgentRunResult(
                    status="need_user_input",
                    summary=summary or "LLM stopped without a tool call or finish_task.",
                    steps_used=step,
                    debug_context=state.to_session_debug_context(self.settings),
                )

            tool_result_blocks = []

            for tool_use in tool_uses:
                tool_use_id = get_tool_use_id(tool_use)
                tool_name = get_tool_use_name(tool_use)
                tool_input = get_tool_use_input(tool_use)

                self._print_tool_call(tool_name, tool_input)
                result = await self.registry.execute(tool_name, tool_input, context)
                self._print_tool_result(result)
                state.record_tool_result(
                    step=step,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    result=result,
                    settings=self.settings,
                )
                tool_result_blocks.append(
                    tool_result_block(
                        tool_use_id,
                        result,
                        max_chars=self.settings.tool_result_max_chars,
                    )
                )

                if tool_name == "finish_task" and result.ok:
                    return AgentRunResult(
                        status=result.data.get("status", "success"),
                        summary=result.data.get("summary", result.message),
                        steps_used=step,
                        debug_context=state.to_session_debug_context(self.settings),
                    )
                elif result.ok:
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1

                if consecutive_failures >= self.settings.max_consecutive_failures:
                    return AgentRunResult(
                        status="failed",
                        summary=(
                            "Maximum consecutive tool failures reached. "
                            "Recommended recovery: call get_current_page_info or query_dom "
                            "to refresh page state before retrying."
                        ),
                        steps_used=step,
                        debug_context=state.to_session_debug_context(self.settings),
                    )
            previous_assistant_blocks = assistant_blocks
            previous_tool_result_blocks = [
                *tool_result_blocks,
                {
                    "type": "text",
                    "text": state.to_context_text(self.settings),
                },
            ]

        return AgentRunResult(
            status="failed",
            summary=f"Maximum step limit reached: {self.settings.max_steps}",
            steps_used=self.settings.max_steps,
            debug_context=state.to_session_debug_context(self.settings),
        )

    def _build_messages(
        self,
        *,
        state: AgentState,
        previous_assistant_blocks: list[dict[str, Any]] | None,
        previous_tool_result_blocks: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        context_message = state.to_context_text(self.settings)
        if previous_assistant_blocks is None or previous_tool_result_blocks is None:
            return [
                {
                    "role": "user",
                    "content": context_message,
                }
            ]
        return [
            {
                "role": "user",
                "content": context_message,
            },
            {
                "role": "assistant",
                "content": previous_assistant_blocks,
            },
            {
                "role": "user",
                "content": previous_tool_result_blocks,
            },
        ]

    def _print_tool_call(self, name: str, tool_input: dict[str, Any]) -> None:
        self.console.print(f"[bold cyan]Using tool:[/bold cyan] {name}")
        self.console.print(
            Panel(
                JSON.from_data(tool_input),
                title="Input",
                border_style="cyan",
            )
        )

    def _print_tool_result(self, result: ToolResult) -> None:
        border_style = "green" if result.ok else "red"
        self.console.print(
            Panel(
                JSON.from_data(result.model_dump(mode="json", exclude_none=True)),
                title="Result",
                border_style=border_style,
            )
        )
