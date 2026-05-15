from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from app.tools.registry import ToolContext
from app.tools.schemas import (
    AskUserConfirmationInput,
    FinishTaskInput,
    TakeScreenshotInput,
    ToolResult,
    WaitInput,
)


async def wait(input_data: BaseModel, context: ToolContext) -> ToolResult:
    args = WaitInput.model_validate(input_data)
    try:
        page = await context.browser.get_active_page()
        await page.wait_for_timeout(args.seconds * 1000)
        return ToolResult.success(
            tool_name="wait",
            message="Wait completed",
            data={"seconds": args.seconds},
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="wait",
            message=f"Failed while waiting: {exc}",
            error_code="wait_failed",
            data={"seconds": args.seconds, "exception_type": type(exc).__name__},
            next_hint="Ensure the active page is available.",
        )


async def take_screenshot(input_data: BaseModel, context: ToolContext) -> ToolResult:
    args = TakeScreenshotInput.model_validate(input_data)
    try:
        page = await context.browser.get_active_page()
        screenshots_dir = Path(context.browser.settings.screenshots_dir)
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = screenshots_dir / f"screenshot_{timestamp}.png"
        await page.screenshot(path=str(path), full_page=args.full_page)

        return ToolResult.success(
            tool_name="take_screenshot",
            message="Screenshot saved",
            data={
                "path": str(path),
                "full_page": args.full_page,
            },
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="take_screenshot",
            message=f"Failed to take screenshot: {exc}",
            error_code="screenshot_failed",
            data={"exception_type": type(exc).__name__},
            next_hint="Check browser session and screenshots directory permissions.",
        )


async def ask_user_confirmation(input_data: BaseModel, context: ToolContext) -> ToolResult:
    args = AskUserConfirmationInput.model_validate(input_data)
    if context.safety_guard is None:
        return ToolResult.failure(
            tool_name="ask_user_confirmation",
            message="Safety guard is not available in this tool context",
            error_code="safety_guard_unavailable",
            data={
                "reason": args.reason,
                "action_description": args.action_description,
            },
            next_hint="Stop with finish_task(status='blocked') because confirmation cannot be collected.",
        )

    approved = context.safety_guard.request_confirmation(
        reason=args.reason,
        action_description=args.action_description,
    )
    if approved:
        return ToolResult.success(
            tool_name="ask_user_confirmation",
            message="User approved the risky action",
            data={
                "approved": True,
                "reason": args.reason,
                "action_description": args.action_description,
            },
        )
    return ToolResult.failure(
        tool_name="ask_user_confirmation",
        message="User declined the risky action",
        error_code="user_declined_confirmation",
        data={
            "approved": False,
            "reason": args.reason,
            "action_description": args.action_description,
        },
        next_hint="Do not perform the risky action. Call finish_task with status='blocked' or 'need_user_input'.",
    )


async def finish_task(input_data: BaseModel, _: ToolContext) -> ToolResult:
    args = FinishTaskInput.model_validate(input_data)
    return ToolResult.success(
        tool_name="finish_task",
        message="Task finished",
        data={
            "status": args.status,
            "summary": args.summary,
        },
    )
