from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from app.config import Settings
from app.tools.observations import get_current_page_info
from app.tools.registry import ToolContext
from app.tools.schemas import EmptyInput


class FakeBodyLocator:
    async def inner_text(self, **_: object) -> str:
        return "visible text " * 100


class FakeInfoPage:
    url = "https://example.test"

    async def title(self) -> str:
        return "Example"

    def locator(self, selector: str) -> FakeBodyLocator:
        assert selector == "body"
        return FakeBodyLocator()


class FakeInfoBrowser:
    def __init__(self) -> None:
        self.settings = Settings(short_visible_text_chars=200)
        self.page = FakeInfoPage()

    async def get_active_page(self) -> FakeInfoPage:
        return self.page


class PlaywrightInfoBrowser:
    def __init__(self, page: object) -> None:
        self.settings = Settings(short_visible_text_chars=500)
        self.page = page

    async def get_active_page(self) -> object:
        return self.page


@pytest.mark.asyncio
async def test_current_page_info_truncates_visible_text() -> None:
    result = await get_current_page_info(
        EmptyInput(),
        ToolContext(browser=FakeInfoBrowser()),  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert len(result.data["short_visible_text"]) <= 200
    assert result.data["short_visible_text"].endswith("...")


@pytest.mark.asyncio
async def test_current_page_info_prefers_active_modal_text() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1000, "height": 700})
        await page.set_content(
            """
            <main>
              <h1>Vacancy page behind modal</h1>
              <button>Background apply button</button>
            </main>
            <div
              id="response-modal"
              role="dialog"
              aria-modal="true"
              style="position:fixed;left:250px;top:100px;width:480px;min-height:240px;background:white;z-index:1000"
            >
              <h2>Response modal</h2>
              <button>Add cover letter</button>
              <button>Apply now</button>
            </div>
            """
        )

        result = await get_current_page_info(
            EmptyInput(),
            ToolContext(browser=PlaywrightInfoBrowser(page)),  # type: ignore[arg-type]
        )
        await browser.close()

    assert result.ok is True
    assert result.data["active_layer_selector"] == "#response-modal"
    assert "Response modal" in result.data["short_visible_text"]
    assert "Add cover letter" in result.data["short_visible_text"]
    assert "Vacancy page behind modal" not in result.data["short_visible_text"]
