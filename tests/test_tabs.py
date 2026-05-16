from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.tools.observations import get_current_page_info
from app.tools.registry import ToolContext, create_default_tool_registry
from app.tools.schemas import EmptyInput


class TabBodyLocator:
    async def inner_text(self, **_: object) -> str:
        return "Inbox\nMessage 1\nMessage 2"


class TabPage:
    def __init__(self, url: str, title: str) -> None:
        self.url = url
        self._title = title
        self.fronted = False

    async def title(self) -> str:
        return self._title

    async def bring_to_front(self) -> None:
        self.fronted = True

    def locator(self, selector: str) -> TabBodyLocator:
        assert selector == "body"
        return TabBodyLocator()


class TabBrowser:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            short_visible_text_chars=2000,
            browser_ui_settle_ms=0,
            browser_load_state_timeout_ms=100,
        )
        self.pages = [
            TabPage("https://mail.example/home", "Mail Home"),
            TabPage("https://mail.example/inbox", "Inbox"),
        ]
        self.active_index = 0

    async def get_active_page(self) -> TabPage:
        return self.pages[self.active_index]

    async def list_pages(self) -> list[dict[str, object]]:
        return [
            {
                "index": index,
                "active": index == self.active_index,
                "url": page.url,
                "title": await page.title(),
            }
            for index, page in enumerate(self.pages)
        ]

    async def switch_to_page(self, index: int) -> TabPage:
        self.active_index = index
        page = self.pages[index]
        await page.bring_to_front()
        return page


class BrokenTabsBrowser(TabBrowser):
    async def list_pages(self) -> list[dict[str, object]]:
        raise RuntimeError("tabs crashed")


@pytest.mark.asyncio
async def test_get_current_page_info_includes_tab_summary() -> None:
    browser = TabBrowser()

    result = await get_current_page_info(
        EmptyInput(),
        ToolContext(browser=browser),  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert result.data["active_tab_index"] == 0
    assert result.data["tabs"][1]["title"] == "Inbox"
    assert result.data["short_visible_text"] == "Inbox\nMessage 1\nMessage 2"


@pytest.mark.asyncio
async def test_switch_tab_changes_active_page() -> None:
    registry = create_default_tool_registry()
    browser = TabBrowser()

    result = await registry.execute(
        "switch_tab",
        {"index": 1},
        ToolContext(browser=browser),  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert browser.active_index == 1
    assert browser.pages[1].fronted is True
    assert result.data["url"] == "https://mail.example/inbox"
    assert result.data["tabs"][1]["active"] is True


@pytest.mark.asyncio
async def test_list_tabs_returns_active_index() -> None:
    registry = create_default_tool_registry()
    browser = TabBrowser()
    browser.active_index = 1

    result = await registry.execute(
        "list_tabs",
        {},
        ToolContext(browser=browser),  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert result.data["active_tab_index"] == 1
    assert result.data["tab_count"] == 2


@pytest.mark.asyncio
async def test_get_current_page_info_reports_tabs_error() -> None:
    browser = BrokenTabsBrowser()

    result = await get_current_page_info(
        EmptyInput(),
        ToolContext(browser=browser),  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert result.data["tabs"] == []
    assert "RuntimeError" in result.data["tabs_error"]
