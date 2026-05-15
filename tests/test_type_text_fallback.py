from __future__ import annotations

from types import SimpleNamespace

import pytest

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


@pytest.mark.asyncio
async def test_type_text_falls_back_to_keyboard_for_custom_editor() -> None:
    browser = FallbackBrowser()

    result = await type_text(
        TypeTextInput(
            selector='div[role="textbox"]',
            text="привет",
            press_enter=False,
            action_description="Type message draft",
        ),
        ToolContext(browser=browser),  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert result.data["method"] == "keyboard"
    assert browser.page.clicked is True
    assert browser.page.keyboard.typed == ["привет"]
    assert browser.page.keyboard.pressed == []
