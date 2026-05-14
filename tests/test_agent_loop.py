from __future__ import annotations

from io import StringIO
from types import SimpleNamespace
from typing import Any

import pytest
from rich.console import Console

from app.agent.loop import MainAgentLoop
from app.config import Settings
from app.tools.registry import create_default_tool_registry


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
