from __future__ import annotations

from app.agent.schemas import AgentRunResult
from app.main import compose_session_task


def test_compose_session_task_keeps_followup_context() -> None:
    effective_task = compose_session_task(
        current_message="Да, продолжай и удали только явный спам",
        session_history=[
            (
                "Прочитай последние 10 писем и найди спам",
                AgentRunResult(
                    status="need_user_input",
                    summary="Found 3 likely spam emails and asked for confirmation.",
                    steps_used=12,
                    debug_context="click_element failed; element_from_point=#overlay",
                ),
            )
        ],
    )

    assert "same open browser session" in effective_task
    assert "Прочитай последние 10 писем" in effective_task
    assert "Да, продолжай" in effective_task
    assert "Found 3 likely spam emails" in effective_task
    assert "element_from_point=#overlay" in effective_task


def test_compose_session_task_first_message_is_unchanged() -> None:
    assert (
        compose_session_task(current_message="Open inbox", session_history=[])
        == "Open inbox"
    )
