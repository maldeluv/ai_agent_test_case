from __future__ import annotations

from io import StringIO
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel
from rich.console import Console

from app.agent.loop import MainAgentLoop
from app.config import Settings
from app.tools.registry import ToolContext, ToolRegistry, create_default_tool_registry
from app.tools.schemas import EmptyInput, FinishTaskInput, ToolResult


class FakeClaudeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        return SimpleNamespace(
            content=[
                {"type": "text", "text": "I can finish this test task."},
                {
                    "type": "tool_use",
                    "id": "toolu_finish",
                    "name": "finish_task",
                    "input": {"status": "success", "summary": "Finished test task"},
                },
            ]
        )


class FailingModelClient:
    async def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        raise RuntimeError("rate limited")


class TwoStepModelClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        if len(self.calls) == 1:
            return SimpleNamespace(
                content=[
                    {
                        "type": "tool_use",
                        "id": "toolu_huge",
                        "name": "huge_tool",
                        "input": {},
                    }
                ]
            )
        return SimpleNamespace(
            content=[
                {
                    "type": "tool_use",
                    "id": "toolu_finish",
                    "name": "finish_task",
                    "input": {"status": "success", "summary": "Done"},
                }
            ]
        )


class AlwaysFailingToolClient:
    def __init__(self) -> None:
        self.calls = 0

    async def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        self.calls += 1
        return SimpleNamespace(
            content=[
                {
                    "type": "tool_use",
                    "id": f"toolu_missing_{self.calls}",
                    "name": "missing_tool",
                    "input": {},
                }
            ]
        )


class TextOnlyModelClient:
    async def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        return SimpleNamespace(
            content=[
                {
                    "type": "text",
                    "text": "Could not find the requested message input.",
                }
            ]
        )


async def huge_tool(_: BaseModel, __: ToolContext) -> ToolResult:
    return ToolResult.success(
        tool_name="huge_tool",
        message="Huge output",
        data={"blob": "x" * 10000},
    )


async def finish_task_for_test(input_data: BaseModel, _: ToolContext) -> ToolResult:
    args = FinishTaskInput.model_validate(input_data)
    return ToolResult.success(
        tool_name="finish_task",
        message="Task finished",
        data={"status": args.status, "summary": args.summary},
    )


def compact_history_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        name="huge_tool",
        description="Returns a huge result.",
        input_model=EmptyInput,
        handler=huge_tool,
    )
    registry.register(
        name="finish_task",
        description="Finish.",
        input_model=FinishTaskInput,
        handler=finish_task_for_test,
    )
    return registry


@pytest.mark.asyncio
async def test_agent_loop_executes_finish_task_tool() -> None:
    client = FakeClaudeClient()
    console = Console(file=StringIO(), force_terminal=False)
    loop = MainAgentLoop(
        settings=Settings(max_steps=3),
        browser=SimpleNamespace(),  # type: ignore[arg-type]
        registry=create_default_tool_registry(),
        client=client,
        console=console,
    )

    result = await loop.run("Finish the test")

    assert result.status == "success"
    assert result.summary == "Finished test task"
    assert result.steps_used == 1
    assert client.calls[0]["tools"]


@pytest.mark.asyncio
async def test_agent_loop_uses_provider_neutral_request_error() -> None:
    console = Console(file=StringIO(), force_terminal=False)
    loop = MainAgentLoop(
        settings=Settings(max_steps=3),
        browser=SimpleNamespace(),  # type: ignore[arg-type]
        registry=create_default_tool_registry(),
        client=FailingModelClient(),
        console=console,
    )

    result = await loop.run("Trigger failure")

    assert result.status == "failed"
    assert result.summary.startswith("LLM request failed:")
    assert "Claude" not in result.summary


@pytest.mark.asyncio
async def test_agent_loop_passes_compact_state_instead_of_raw_history() -> None:
    client = TwoStepModelClient()
    settings = Settings(
        max_steps=3,
        agent_recent_actions_limit=2,
        agent_execution_summary_max_chars=400,
        agent_action_max_chars=160,
        tool_result_max_chars=500,
    )
    console = Console(file=StringIO(), force_terminal=False)
    loop = MainAgentLoop(
        settings=settings,
        browser=SimpleNamespace(),  # type: ignore[arg-type]
        registry=compact_history_registry(),
        client=client,
        console=console,
    )

    result = await loop.run("Use compact context")
    second_call_messages = client.calls[1]["messages"]
    serialized_messages = str(second_call_messages)

    assert result.status == "success"
    assert len(second_call_messages) == 3
    assert "Compact execution summary" in serialized_messages
    assert "x" * 1000 not in serialized_messages


@pytest.mark.asyncio
async def test_agent_loop_stops_after_max_consecutive_failures() -> None:
    client = AlwaysFailingToolClient()
    console = Console(file=StringIO(), force_terminal=False)
    loop = MainAgentLoop(
        settings=Settings(max_steps=5, max_consecutive_failures=2),
        browser=SimpleNamespace(),  # type: ignore[arg-type]
        registry=create_default_tool_registry(),
        client=client,
        console=console,
    )

    result = await loop.run("Trigger repeated failures")

    assert result.status == "failed"
    assert "Maximum consecutive tool failures" in result.summary
    assert "query_dom" in result.summary
    assert client.calls == 2


@pytest.mark.asyncio
async def test_agent_loop_uses_text_only_response_as_summary() -> None:
    console = Console(file=StringIO(), force_terminal=False)
    loop = MainAgentLoop(
        settings=Settings(max_steps=3),
        browser=SimpleNamespace(),  # type: ignore[arg-type]
        registry=create_default_tool_registry(),
        client=TextOnlyModelClient(),
        console=console,
    )

    result = await loop.run("Trigger text only response")

    assert result.status == "need_user_input"
    assert result.summary == "Could not find the requested message input."
