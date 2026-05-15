from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from app.browser.content_extractor import ContentExtractor
from app.config import Settings


def fake_inbox_rows() -> str:
    rows = []
    for index in range(1, 11):
        sender = "Promo Shop" if index in {2, 5, 8} else f"Important Sender {index}"
        subject = "Huge sale today" if index in {2, 5, 8} else f"Project update {index}"
        snippet = "Limited offer, unsubscribe link inside" if index in {2, 5, 8} else "Useful work details"
        rows.append(
            f"""
            <div id="mail-{index}" class="mail-row" role="listitem" tabindex="0">
              <input type="checkbox" aria-label="Select email {index}">
              <span class="sender">{sender}</span>
              <span class="subject">{subject}</span>
              <span class="snippet">{snippet}</span>
              <button aria-label="More actions {index}">...</button>
            </div>
            """
        )
    return "\n".join(rows)


@pytest.mark.asyncio
async def test_content_extractor_reads_fake_inbox_rows_with_controls() -> None:
    settings = Settings(
        content_max_items=10,
        content_max_text_chars=240,
        content_max_controls_per_item=4,
    )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        await page.set_content(
            f"""
            <main>
              <h1>Inbox</h1>
              <div id="inbox" role="list">{fake_inbox_rows()}</div>
            </main>
            <style>
              .mail-row {{
                display: grid;
                grid-template-columns: 40px 180px 240px 1fr 40px;
                width: 900px;
                min-height: 42px;
                cursor: pointer;
              }}
            </style>
            """
        )

        items = await ContentExtractor(settings).extract(
            page,
            query="last 10 inbox emails sender subject snippet",
            max_items=10,
        )
        await browser.close()

    assert len(items) == 10
    assert items[0].selector == "#mail-1"
    assert "Important Sender 1" in items[0].text
    assert "Project update 1" in items[0].text
    assert any(control.kind == "checkbox" for control in items[0].controls)


@pytest.mark.asyncio
async def test_content_extractor_limits_total_payload_but_keeps_repeated_rows() -> None:
    settings = Settings(
        content_max_items=20,
        content_max_text_chars=120,
        content_max_total_chars=2500,
    )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        await page.set_content(
            f"""
            <main>
              <div id="inbox" role="list">{fake_inbox_rows()}</div>
            </main>
            <style>.mail-row {{ width: 900px; min-height: 42px; }}</style>
            """
        )

        items = await ContentExtractor(settings).extract(
            page,
            query="inbox email rows",
            max_items=20,
        )
        await browser.close()

    assert 1 <= len(items) < 20
    assert all(len(item.text) <= settings.content_max_text_chars for item in items)
    assert items[0].selector == "#mail-1"
