from __future__ import annotations

from types import SimpleNamespace

import pytest
from playwright.async_api import async_playwright

from app.config import Settings
from app.subagents.vision_agent import VisionSubAgent
from app.tools.registry import ToolContext
from app.tools.schemas import ObserveScreenshotInput, ScreenshotObservationData, VisualRegion
from app.tools.vision import observe_screenshot


class FakeVisionClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.requests: list[dict[str, object]] = []

    async def create_message(self, **request: object) -> object:
        self.requests.append(request)
        text = self.responses.pop(0)
        return SimpleNamespace(content=[{"type": "text", "text": text}])


class PlaywrightVisionBrowser:
    def __init__(self, page: object, settings: Settings) -> None:
        self.page = page
        self.settings = settings

    async def get_active_page(self) -> object:
        return self.page


@pytest.mark.asyncio
async def test_vision_sub_agent_sends_image_and_parses_json() -> None:
    client = FakeVisionClient(
        [
            """
            {
              "answer": "A centered modal is visible.",
              "visible_regions": [
                {
                  "region": "center",
                  "description": "Modal with action buttons",
                  "evidence": "White box over dimmed page"
                }
              ],
              "suggested_next_step": "Use query_dom for the modal buttons.",
              "confidence": 0.82
            }
            """
        ]
    )

    result = await VisionSubAgent(Settings(), client=client).analyze(
        question="Is there a modal?",
        image_bytes=b"fake-image",
        media_type="image/jpeg",
    )

    assert result.answer == "A centered modal is visible."
    assert result.visible_regions[0].region == "center"
    assert result.confidence == 0.82
    content = client.requests[0]["messages"][0]["content"]  # type: ignore[index]
    assert content[1]["type"] == "image"  # type: ignore[index]
    assert content[1]["source"]["media_type"] == "image/jpeg"  # type: ignore[index]


@pytest.mark.asyncio
async def test_vision_sub_agent_repairs_invalid_json() -> None:
    client = FakeVisionClient(
        [
            "not json",
            """
            {
              "answer": "The page shows a search result grid.",
              "visible_regions": [],
              "suggested_next_step": "Use query_dom for result controls.",
              "confidence": 0.7
            }
            """,
        ]
    )

    result = await VisionSubAgent(Settings(), client=client).analyze(
        question="What changed?",
        image_bytes=b"fake-image",
        media_type="image/jpeg",
    )

    assert result.answer == "The page shows a search result grid."
    assert len(client.requests) == 2


@pytest.mark.asyncio
async def test_observe_screenshot_uses_vision_agent_and_saves_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    class FakeVisionSubAgent:
        def __init__(self, _: Settings) -> None:
            pass

        async def analyze(self, **kwargs: object) -> ScreenshotObservationData:
            assert kwargs["media_type"] == "image/jpeg"
            assert len(kwargs["image_bytes"]) > 0
            return ScreenshotObservationData(
                answer="The modal is visible.",
                visible_regions=[
                    VisualRegion(
                        region="center",
                        description="A modal dialog",
                        evidence="It overlays the page",
                    )
                ],
                suggested_next_step="Use query_dom to find modal buttons.",
                confidence=0.9,
            )

    monkeypatch.setattr("app.tools.vision.VisionSubAgent", FakeVisionSubAgent)
    settings = Settings(screenshots_dir=tmp_path)  # type: ignore[arg-type]

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 640, "height": 480})
        await page.set_content("<main><h1>Visible page</h1></main>")

        result = await observe_screenshot(
            ObserveScreenshotInput(question="What is visible?"),
            ToolContext(browser=PlaywrightVisionBrowser(page, settings)),  # type: ignore[arg-type]
        )
        await browser.close()

    assert result.ok is True
    assert result.data["answer"] == "The modal is visible."
    assert result.data["confidence"] == 0.9
    assert result.data["path"]


@pytest.mark.asyncio
async def test_observe_screenshot_respects_disabled_config() -> None:
    class FakePage:
        pass

    settings = Settings(vision_observation_enabled=False)
    result = await observe_screenshot(
        ObserveScreenshotInput(question="What is visible?"),
        ToolContext(browser=PlaywrightVisionBrowser(FakePage(), settings)),  # type: ignore[arg-type]
    )

    assert result.ok is False
    assert result.error_code == "vision_disabled"
