from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from app.subagents.vision_agent import VisionSubAgent
from app.tools.registry import ToolContext
from app.tools.schemas import ObserveScreenshotInput, ToolResult


async def observe_screenshot(input_data: BaseModel, context: ToolContext) -> ToolResult:
    args = ObserveScreenshotInput.model_validate(input_data)
    settings = context.browser.settings
    if not settings.vision_observation_enabled:
        return ToolResult.failure(
            tool_name="observe_screenshot",
            message="Vision screenshot observation is disabled by configuration.",
            error_code="vision_disabled",
            data={"question": args.question},
            next_hint="Use DOM/text tools such as get_current_page_info, query_dom, or get_element_info.",
        )

    try:
        page = await context.browser.get_active_page()
        image_bytes = await page.screenshot(
            full_page=args.full_page,
            type="jpeg",
            quality=settings.vision_screenshot_quality,
        )
        if len(image_bytes) > settings.vision_max_screenshot_bytes:
            return ToolResult.failure(
                tool_name="observe_screenshot",
                message="Screenshot is too large for configured vision observation limit.",
                error_code="screenshot_too_large",
                data={
                    "question": args.question,
                    "full_page": args.full_page,
                    "bytes": len(image_bytes),
                    "max_bytes": settings.vision_max_screenshot_bytes,
                },
                next_hint=(
                    "Retry with full_page=false or use DOM/text tools for targeted inspection."
                ),
            )

        saved_path = None
        if args.save_screenshot:
            screenshots_dir = Path(settings.screenshots_dir)
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            saved_path = screenshots_dir / f"vision_{timestamp}.jpg"
            saved_path.write_bytes(image_bytes)

        vision_agent = VisionSubAgent(settings)
        analysis = await vision_agent.analyze(
            question=args.question,
            image_bytes=image_bytes,
            media_type="image/jpeg",
        )
        return ToolResult.success(
            tool_name="observe_screenshot",
            message="Screenshot visual observation completed",
            data={
                "question": args.question,
                "full_page": args.full_page,
                "path": str(saved_path) if saved_path is not None else None,
                "bytes": len(image_bytes),
                "answer": analysis.answer,
                "visible_regions": [
                    region.model_dump(mode="json")
                    for region in analysis.visible_regions
                ],
                "suggested_next_step": analysis.suggested_next_step,
                "confidence": analysis.confidence,
                "error_code": analysis.error_code,
                "raw_preview": analysis.raw_preview,
                "usage_hint": (
                    "Use this visual result as fallback context only. Get exact selectors "
                    "through query_dom/get_element_info before clicking or typing."
                ),
            },
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="observe_screenshot",
            message=f"Failed to observe screenshot: {exc}",
            error_code="observe_screenshot_failed",
            data={"question": args.question, "exception_type": type(exc).__name__},
            next_hint=(
                "Use get_current_page_info/query_dom first, or retry observe_screenshot "
                "with a narrower visual question."
            ),
        )
