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


class ScrollableLocator:
    async def evaluate(self, _: str, delta_y: int) -> dict[str, object]:
        return {
            "scrollable": True,
            "before": {"scrollTop": 0},
            "after": {"scrollTop": delta_y},
            "scrollHeight": 2000,
            "clientHeight": 500,
        }


class ScrollablePage:
    def locator(self, selector: str) -> ScrollableLocator:
        assert selector == "#list"
        return ScrollableLocator()


class ScrollableBrowser:
    def __init__(self) -> None:
        self.settings = SimpleNamespace()
        self.page = ScrollablePage()

    async def get_active_page(self) -> ScrollablePage:
        return self.page


class FakeBackResponse:
    status = 200


class BackPage:
    url = "https://example.test/inbox"

    async def go_back(self, **_: object) -> FakeBackResponse:
        self.url = "https://example.test"
        return FakeBackResponse()

    async def title(self) -> str:
        return "Example"


class BackBrowser:
    def __init__(self) -> None:
        self.settings = SimpleNamespace()
        self.page = BackPage()

    async def get_active_page(self) -> BackPage:
        return self.page


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


@pytest.mark.asyncio
async def test_scroll_element_returns_scroll_state() -> None:
    registry = create_default_tool_registry()

    result = await registry.execute(
        "scroll_element",
        {"selector": "#list", "direction": "down", "amount": 500},
        ToolContext(browser=ScrollableBrowser()),  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert result.data["scroll_state"]["after"]["scrollTop"] == 500


@pytest.mark.asyncio
async def test_go_back_returns_current_page_info() -> None:
    registry = create_default_tool_registry()

    result = await registry.execute(
        "go_back",
        {},
        ToolContext(browser=BackBrowser()),  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert result.data["url"] == "https://example.test"
    assert result.data["had_history_entry"] is True
