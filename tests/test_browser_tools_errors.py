from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.tools.registry import ToolContext, create_default_tool_registry


class FailingLocator:
    async def click(self, **_: object) -> None:
        raise RuntimeError("element is not clickable")


class FakePage:
    url = "https://example.test"
    mouse = SimpleNamespace()

    async def title(self) -> str:
        return "Example"

    def locator(self, _: str) -> FailingLocator:
        return FailingLocator()


class FakeBrowser:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(screenshots_dir="screenshots")
        self.page = FakePage()

    async def get_active_page(self) -> FakePage:
        return self.page


class NotStartedBrowser:
    async def get_active_page(self) -> None:
        raise RuntimeError("browser is not started")


@pytest.mark.asyncio
async def test_failed_click_returns_structured_tool_result() -> None:
    registry = create_default_tool_registry()

    result = await registry.execute(
        "click_element",
        {"selector": "#submit"},
        ToolContext(browser=FakeBrowser()),  # type: ignore[arg-type]
    )

    assert result.ok is False
    assert result.error_code == "click_failed"
    assert result.data["selector"] == "#submit"
    assert result.next_hint is not None


@pytest.mark.asyncio
async def test_page_info_without_browser_returns_structured_tool_result() -> None:
    registry = create_default_tool_registry()

    result = await registry.execute(
        "get_current_page_info",
        {},
        ToolContext(browser=NotStartedBrowser()),  # type: ignore[arg-type]
    )

    assert result.ok is False
    assert result.error_code == "page_info_failed"
    assert result.data["exception_type"] == "RuntimeError"
