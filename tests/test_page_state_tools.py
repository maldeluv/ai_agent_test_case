from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from app.config import Settings
from app.tools.observations import get_element_info, wait_for_page_state
from app.tools.registry import ToolContext
from app.tools.schemas import GetElementInfoInput, WaitForPageStateInput


class PlaywrightObservationBrowser:
    def __init__(self, page: object) -> None:
        self.settings = Settings(short_visible_text_chars=500)
        self.page = page

    async def get_active_page(self) -> object:
        return self.page


@pytest.mark.asyncio
async def test_get_element_info_reads_value_state_and_rect() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 800, "height": 600})
        await page.set_content(
            """
            <main>
              <input id="qty" type="number" value="1" aria-label="Quantity">
              <button id="submit" disabled>Submit order</button>
            </main>
            """
        )

        qty_result = await get_element_info(
            GetElementInfoInput(selector="#qty"),
            ToolContext(browser=PlaywrightObservationBrowser(page)),  # type: ignore[arg-type]
        )
        button_result = await get_element_info(
            GetElementInfoInput(selector="#submit"),
            ToolContext(browser=PlaywrightObservationBrowser(page)),  # type: ignore[arg-type]
        )
        await browser.close()

    assert qty_result.ok is True
    assert qty_result.data["element"]["value"] == "1"
    assert qty_result.data["element"]["aria_label"] == "Quantity"
    assert qty_result.data["element"]["visible"] is True
    assert qty_result.data["element"]["rect"]["width"] > 0
    assert button_result.ok is True
    assert button_result.data["element"]["disabled"] is True


@pytest.mark.asyncio
async def test_wait_for_page_state_waits_for_text_and_selector() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(
            """
            <main>
              <button id="add">Add</button>
              <span id="status"></span>
              <span id="counter" hidden>1</span>
            </main>
            """
        )
        await page.evaluate(
            """
            () => {
              setTimeout(() => {
                document.querySelector('#status').textContent = 'Added to cart';
                document.querySelector('#counter').hidden = false;
              }, 100);
            }
            """
        )

        result = await wait_for_page_state(
            WaitForPageStateInput(
                selector="#counter",
                text="Added to cart",
                timeout_ms=2000,
            ),
            ToolContext(browser=PlaywrightObservationBrowser(page)),  # type: ignore[arg-type]
        )
        await browser.close()

    assert result.ok is True
    assert result.data["matched"] == {"selector": True, "text": True}
    assert "Added to cart" in result.data["short_visible_text"]


@pytest.mark.asyncio
async def test_wait_for_page_state_returns_timeout_failure() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content("<main>Ready</main>")

        result = await wait_for_page_state(
            WaitForPageStateInput(text="Never appears", timeout_ms=150),
            ToolContext(browser=PlaywrightObservationBrowser(page)),  # type: ignore[arg-type]
        )
        await browser.close()

    assert result.ok is False
    assert result.error_code == "page_state_timeout"
    assert result.next_hint is not None
