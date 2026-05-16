from __future__ import annotations

from app.agent.schemas import AgentRunResult
from app.main import compose_session_task
from app.safety import SafetyGuard


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


def test_compose_session_task_includes_pending_approval_context() -> None:
    effective_task = compose_session_task(
        current_message="да",
        session_history=[],
        pending_approvals=[
            {
                "approval_id": "approval-1",
                "tool_name": "click_element",
                "action_description": "Delete selected spam emails",
                "target_context": "2 emails: Promo Shop, Fake Lottery",
            }
        ],
    )

    assert "Pending risky approvals" in effective_task
    assert "approval-1" in effective_task
    assert "Delete selected spam emails" in effective_task


def test_safety_guard_followup_yes_approves_single_pending_action() -> None:
    guard = SafetyGuard(confirmation_callback=lambda *_: True)
    blocked = guard.check_tool_call(
        tool_name="click_element",
        arguments={
            "selector": "#delete",
            "action_description": "Delete email",
        },
        browser_context={"active_url": "https://mail.example/inbox", "active_tab_index": 0},
    )

    approved_id = guard.approve_followup_text("да")

    assert blocked is not None
    assert approved_id == blocked.data["approval_id"]
    assert guard.pending_approval_count() == 1
