from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from app.browser.dom_extractor import DOMExtractor
from app.config import Settings


@pytest.mark.asyncio
async def test_dom_extractor_includes_custom_chat_editors() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(
            """
            <main>
              <div
                role="textbox"
                contenteditable="plaintext-only"
                aria-label="Напишите сообщение"
                aria-multiline="true"
                data-testid="composer"
              ></div>
              <button aria-label="Отправить">Send</button>
            </main>
            """
        )

        candidates = await DOMExtractor(Settings()).extract(page)
        await browser.close()

    textbox = next(candidate for candidate in candidates if candidate.role == "textbox")
    assert textbox.contenteditable == "plaintext-only"
    assert textbox.aria_label == "Напишите сообщение"
    assert textbox.aria_multiline == "true"
    assert textbox.data_testid == "composer"
    assert textbox.is_editable is True


@pytest.mark.asyncio
async def test_dom_extractor_prioritizes_query_matches_under_payload_limit() -> None:
    settings = Settings(
        dom_max_elements=10,
        dom_max_text_chars=80,
        dom_max_total_chars=1800,
    )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        noisy_buttons = "\n".join(
            f'<button class="{"x" * 240}">Menu item {index}</button>'
            for index in range(30)
        )
        await page.set_content(
            f"""
            <main>
              <nav>{noisy_buttons}</nav>
              <section>
                <div id="favorite-chat" tabindex="0">
                  <span>Избранное</span>
                  <span>Последнее сообщение</span>
                </div>
              </section>
            </main>
            """
        )

        candidates = await DOMExtractor(settings).extract(page, query="чат Избранное")
        await browser.close()

    favorite = next(
        candidate
        for candidate in candidates
        if "Избранное" in candidate.text or "Избранное" in candidate.nearby_text
    )
    assert favorite.selector == "#favorite-chat"
    assert favorite.query_match_score >= 1


@pytest.mark.asyncio
async def test_dom_extractor_includes_pointer_cursor_spa_controls() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(
            """
            <main>
              <div id="open-chat" style="cursor: pointer">Open saved chat</div>
            </main>
            """
        )

        candidates = await DOMExtractor(Settings()).extract(page, query="open saved chat")
        await browser.close()

    spa_control = next(candidate for candidate in candidates if candidate.selector == "#open-chat")
    assert spa_control.is_clickable is True
    assert spa_control.query_match_score >= 2


@pytest.mark.asyncio
async def test_dom_extractor_excludes_elements_outside_viewport() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 800, "height": 600})
        await page.set_content(
            """
            <main style="height: 2000px">
              <button id="offscreen" style="position:absolute;top:1400px">Delete email</button>
              <button id="onscreen">Search</button>
            </main>
            """
        )

        candidates = await DOMExtractor(Settings()).extract(page, query="delete email")
        await browser.close()

    assert all(candidate.selector != "#offscreen" for candidate in candidates)
    assert any(candidate.selector == "#onscreen" for candidate in candidates)


@pytest.mark.asyncio
async def test_dom_extractor_marks_center_occluded() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 800, "height": 600})
        await page.set_content(
            """
            <button id="target" style="position:absolute;left:20px;top:20px;width:180px;height:60px">
              Delete email
            </button>
            <div id="overlay" style="position:absolute;left:20px;top:20px;width:180px;height:60px;z-index:10">
              Overlay
            </div>
            """
        )

        candidates = await DOMExtractor(Settings()).extract(page, query="delete email")
        await browser.close()

    target = next(candidate for candidate in candidates if candidate.selector == "#target")
    assert target.in_viewport is True
    assert target.center_occluded is True
    assert target.rect["width"] == 180


@pytest.mark.asyncio
async def test_dom_extractor_marks_nth_of_type_selector_low_stability() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content("<main><button>Plain action</button></main>")

        candidates = await DOMExtractor(Settings()).extract(page, query="plain action")
        await browser.close()

    plain = next(candidate for candidate in candidates if "Plain action" in candidate.text)
    assert ":nth-of-type(" in plain.selector
    assert plain.selector_stability == "low"
