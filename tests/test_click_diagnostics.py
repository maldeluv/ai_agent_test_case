from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from app.config import Settings
from app.tools.interactions import click_element
from app.tools.registry import ToolContext
from app.tools.schemas import ClickElementInput


class PlaywrightBrowser:
    def __init__(self, page: object) -> None:
        self.settings = Settings(
            browser_action_timeout_ms=800,
            browser_ui_settle_ms=0,
            browser_load_state_timeout_ms=100,
        )
        self.page = page

    async def get_active_page(self) -> object:
        return self.page


@pytest.mark.asyncio
async def test_click_failure_returns_element_from_point_diagnostics() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(
            """
            <button id="target" style="position:absolute;left:20px;top:20px;width:180px;height:60px">
              Open chat
            </button>
            <div id="overlay" style="position:absolute;left:0;top:0;width:240px;height:110px;z-index:5">
              Loading overlay
            </div>
            """
        )

        result = await click_element(
            ClickElementInput(selector="#target"),
            ToolContext(browser=PlaywrightBrowser(page)),  # type: ignore[arg-type]
        )
        await browser.close()

    assert result.ok is False
    assert result.error_code == "click_failed"
    diagnostics = result.data["click_diagnostics"]
    assert diagnostics["intercepted"] is True
    assert diagnostics["element_from_point"]["selector"] == "#overlay"


@pytest.mark.asyncio
async def test_click_position_can_avoid_center_overlay() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(
            """
            <button
              id="target"
              onclick="window.clicked = true"
              style="position:absolute;left:20px;top:20px;width:240px;height:60px"
            >
              Open chat
            </button>
            <div
              id="center-overlay"
              style="position:absolute;left:100px;top:20px;width:120px;height:60px;z-index:5"
            >
              Center overlay
            </div>
            """
        )

        result = await click_element(
            ClickElementInput(selector="#target", position="left"),
            ToolContext(browser=PlaywrightBrowser(page)),  # type: ignore[arg-type]
        )
        clicked = await page.evaluate("Boolean(window.clicked)")
        await browser.close()

    assert result.ok is True
    assert clicked is True
    assert result.data["position"] == "left"


@pytest.mark.asyncio
async def test_nearest_clickable_ancestor_strategy_reports_clicked_selector() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(
            """
            <div
              id="row"
              role="button"
              onclick="window.clicked = 'row'"
              style="width:240px;height:60px;cursor:pointer"
            >
              <span id="row-text">Александр Скрипник</span>
            </div>
            """
        )

        result = await click_element(
            ClickElementInput(
                selector="#row-text",
                strategy="nearest_clickable_ancestor",
            ),
            ToolContext(browser=PlaywrightBrowser(page)),  # type: ignore[arg-type]
        )
        clicked = await page.evaluate("window.clicked")
        await browser.close()

    assert result.ok is True
    assert clicked == "row"
    assert result.data["method"] == "nearest_clickable_ancestor"
    assert result.data["clicked_selector"] == "#row"
