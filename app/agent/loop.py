from __future__ import annotations

from typing import Any, Protocol

from rich.console import Console
from rich.json import JSON
from rich.panel import Panel

from app.agent.prompts import MAIN_AGENT_SYSTEM_PROMPT
from app.agent.schemas import AgentRunResult
from app.browser.session import BrowserSession
from app.config import Settings
from app.llm.claude_client import ClaudeClient
from app.llm.tool_use import (
    content_block_to_dict,
    get_block_text,
    get_block_type,
    get_tool_use_id,
    get_tool_use_input,
    get_tool_use_name,
    tool_definitions_for_claude,
    tool_result_block,
)
from app.tools.registry import ToolContext, ToolRegistry
from app.tools.schemas import ToolResult
from app.utils.logger import get_console, get_logger


class ClaudeMessageClient(Protocol):
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
        client: ClaudeMessageClient | None = None,
        console: Console | None = None,
    ) -> None:
        self.settings = settings
        self.browser = browser
        self.registry = registry
        self.client = client or ClaudeClient(settings)
        self.console = console or get_console()
        self._logger = get_logger(__name__)

    async def run(self, user_task: str) -> AgentRunResult:
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": user_task,
            }
        ]
        tools = tool_definitions_for_claude(self.registry)
        context = ToolContext(browser=self.browser)

        for step in range(1, self.settings.max_steps + 1):
            self.console.rule(f"Agent Step {step}")
            try:
                response = await self.client.create_message(
                    system=MAIN_AGENT_SYSTEM_PROMPT,
                    messages=messages,
                    tools=tools,
                )
            except Exception as exc:
                self._logger.exception("Claude request failed")
                return AgentRunResult(
                    status="failed",
                    summary=f"Claude request failed: {exc}",
                    steps_used=step - 1,
                )

            assistant_blocks = [
                content_block_to_dict(block) for block in getattr(response, "content", [])
            ]
            messages.append({"role": "assistant", "content": assistant_blocks})

            tool_uses = []
            for block in getattr(response, "content", []):
                block_type = get_block_type(block)
                if block_type == "text":
                    text = get_block_text(block).strip()
                    if text:
                        self.console.print(f"[bold]Assistant:[/bold] {text}")
                elif block_type == "tool_use":
                    tool_uses.append(block)

            if not tool_uses:
                return AgentRunResult(
                    status="need_user_input",
                    summary="Claude stopped without a tool call or finish_task.",
                    steps_used=step,
                )

            tool_result_blocks = []
            final_result: AgentRunResult | None = None

            for tool_use in tool_uses:
                tool_use_id = get_tool_use_id(tool_use)
                tool_name = get_tool_use_name(tool_use)
                tool_input = get_tool_use_input(tool_use)

                self._print_tool_call(tool_name, tool_input)
                result = await self.registry.execute(tool_name, tool_input, context)
                self._print_tool_result(result)
                tool_result_blocks.append(tool_result_block(tool_use_id, result))

                if tool_name == "finish_task" and result.ok:
                    final_result = AgentRunResult(
                        status=result.data.get("status", "success"),
                        summary=result.data.get("summary", result.message),
                        steps_used=step,
                    )

            messages.append({"role": "user", "content": tool_result_blocks})

            if final_result is not None:
                return final_result

        return AgentRunResult(
            status="failed",
            summary=f"Maximum step limit reached: {self.settings.max_steps}",
            steps_used=self.settings.max_steps,
        )

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
