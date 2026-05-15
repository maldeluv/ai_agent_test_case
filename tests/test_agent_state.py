from __future__ import annotations

from app.agent.state import AgentState
from app.config import Settings
from app.tools.schemas import ToolResult


def test_agent_state_limits_recent_actions_and_summary() -> None:
    settings = Settings(
        agent_recent_actions_limit=2,
        agent_execution_summary_max_chars=220,
        agent_action_max_chars=120,
    )
    state = AgentState(user_task="Do the task")

    for step in range(5):
        state.record_tool_result(
            step=step,
            tool_name="test_tool",
            tool_input={"payload": "x" * 500},
            result=ToolResult.success(
                tool_name="test_tool",
                message="Completed " + ("y" * 500),
                data={"result": "z" * 500},
            ),
            settings=settings,
        )

    assert len(state.recent_actions) == 2
    assert len(state.execution_summary) <= settings.agent_execution_summary_max_chars
    assert "Do the task" in state.to_context_text(settings)
