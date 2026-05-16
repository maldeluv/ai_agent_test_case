from __future__ import annotations

from types import SimpleNamespace

import pytest
from playwright.async_api import async_playwright

from app.config import Settings
from app.tools.interactions import type_text
from app.tools.registry import ToolContext
from app.tools.schemas import TypeTextInput


class FallbackLocator:
    def __init__(self, page: "FallbackPage") -> None:
        self.page = page

    async def fill(self, *_: object, **__: object) -> None:
        raise RuntimeError("fill is not supported for this editor")

    async def click(self, **_: object) -> None:
        self.page.clicked = True


class FakeKeyboard:
    def __init__(self) -> None:
        self.typed: list[str] = []
        self.pressed: list[str] = []

    async def type(self, text: str, **_: object) -> None:
        self.typed.append(text)

    async def press(self, key: str) -> None:
        self.pressed.append(key)


class FallbackPage:
    def __init__(self) -> None:
        self.clicked = False
        self.keyboard = FakeKeyboard()

    def locator(self, _: str) -> FallbackLocator:
        return FallbackLocator(self)


class FallbackBrowser:
    def __init__(self) -> None:
        self.settings = SimpleNamespace()
        self.page = FallbackPage()

    async def get_active_page(self) -> FallbackPage:
        return self.page


class VerifyingLocator:
    def __init__(self, page: "VerifyingPage") -> None:
        self.page = page

    async def wait_for(self, **_: object) -> None:
        return None

    async def scroll_into_view_if_needed(self, **_: object) -> None:
        return None

    async def fill(self, text: str, **_: object) -> None:
        self.page.fill_attempts.append(text)
        if self.page.fill_persists:
            self.page.text = text

    async def press(self, key: str, **_: object) -> None:
        self.page.pressed.append(key)
        if key == "Enter":
            self.page.text = self.page.remaining_after_enter

    async def evaluate(self, *_: object) -> str:
        return self.page.text


class VerifyingPage:
    def __init__(self, *, fill_persists: bool, remaining_after_enter: str = "") -> None:
        self.text = ""
        self.fill_persists = fill_persists
        self.remaining_after_enter = remaining_after_enter
        self.fill_attempts: list[str] = []
        self.pressed: list[str] = []

    def locator(self, _: str) -> VerifyingLocator:
        return VerifyingLocator(self)


class VerifyingBrowser:
    def __init__(self, page: VerifyingPage) -> None:
        self.settings = SimpleNamespace(
            browser_action_timeout_ms=1000,
            browser_ui_settle_ms=0,
            browser_load_state_timeout_ms=100,
        )
        self.page = page

    async def get_active_page(self) -> VerifyingPage:
        return self.page


class PlaywrightBrowser:
    def __init__(self, page: object) -> None:
        self.settings = Settings(
            browser_action_timeout_ms=1000,
            browser_ui_settle_ms=0,
            browser_load_state_timeout_ms=100,
        )
        self.page = page

    async def get_active_page(self) -> object:
        return self.page


@pytest.mark.asyncio
async def test_type_text_falls_back_to_keyboard_for_custom_editor() -> None:
    browser = FallbackBrowser()

    result = await type_text(
        TypeTextInput(
            selector='div[role="textbox"]',
            text="hello",
            press_enter=False,
            action_description="Type message draft",
        ),
        ToolContext(browser=browser),  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert result.data["method"] == "keyboard"
    assert browser.page.clicked is True
    assert browser.page.keyboard.typed == ["hello"]
    assert browser.page.keyboard.pressed == []


@pytest.mark.asyncio
async def test_type_text_fails_when_text_is_not_observed() -> None:
    page = VerifyingPage(fill_persists=False)

    result = await type_text(
        TypeTextInput(
            selector='div[role="textbox"]',
            text="hello",
            press_enter=False,
            action_description="Type message draft",
        ),
        ToolContext(browser=VerifyingBrowser(page)),  # type: ignore[arg-type]
    )

    assert result.ok is False
    assert result.error_code == "type_failed"
    assert result.data["verification"]["status"] == "text_not_observed"


@pytest.mark.asyncio
async def test_type_text_enter_reports_submission_attempt_requires_observation() -> None:
    page = VerifyingPage(fill_persists=True, remaining_after_enter="")

    result = await type_text(
        TypeTextInput(
            selector='div[role="textbox"]',
            text="hello",
            press_enter=True,
            action_description="Type message and press Enter to send",
        ),
        ToolContext(browser=VerifyingBrowser(page)),  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert result.data["enter_pressed"] is True
    assert result.data["text_observed_before_enter"] == "hello"
    assert result.data["text_remaining_after_enter"] == ""
    assert result.data["verification"]["requires_follow_up_observation"] is True
    assert result.data["verification"]["status"] == "submitted_attempted_requires_observation"


@pytest.mark.asyncio
async def test_type_text_verifies_real_contenteditable_editor() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(
            """
            <main>
              <div
                id="editor"
                role="textbox"
                contenteditable="true"
                aria-label="Message"
                style="min-height: 40px"
              ></div>
            </main>
            """
        )

        result = await type_text(
            TypeTextInput(
                selector="#editor",
                text="hello from contenteditable",
                press_enter=False,
                action_description="Type message draft",
            ),
            ToolContext(browser=PlaywrightBrowser(page)),  # type: ignore[arg-type]
        )
        editor_text = await page.locator("#editor").inner_text()
        await browser.close()

    assert result.ok is True
    assert result.data["verification"]["status"] == "text_observed"
    assert result.data["text_observed_before_enter"] == "hello from contenteditable"
    assert editor_text == "hello from contenteditable"
