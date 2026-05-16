from __future__ import annotations

import asyncio

import pytest

from app.browser.session import BrowserSession
from app.config import Settings


class FakePage:
    def __init__(self, url: str, title: str = "") -> None:
        self.url = url
        self._title = title
        self.closed = False
        self.fronted = False
        self.handlers: dict[str, object] = {}

    def is_closed(self) -> bool:
        return self.closed

    def on(self, event: str, handler: object) -> None:
        self.handlers[event] = handler

    async def bring_to_front(self) -> None:
        self.fronted = True

    async def title(self) -> str:
        return self._title


class FakeContext:
    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages

    async def new_page(self) -> FakePage:
        page = FakePage("about:blank")
        self.pages.append(page)
        return page


@pytest.mark.asyncio
async def test_browser_session_tracks_new_tab_as_active() -> None:
    old_page = FakePage("https://mail.example/home", "Home")
    new_page = FakePage("https://mail.example/inbox", "Inbox")
    session = BrowserSession(Settings())
    session._context = FakeContext([old_page, new_page])  # type: ignore[assignment]
    session._active_page = old_page  # type: ignore[assignment]

    session._handle_new_page(new_page)  # type: ignore[arg-type]
    active = await session.get_active_page()

    assert active is new_page
    assert new_page.fronted is True


@pytest.mark.asyncio
async def test_browser_session_switches_to_requested_tab() -> None:
    first_page = FakePage("https://mail.example/home", "Home")
    second_page = FakePage("https://mail.example/inbox", "Inbox")
    session = BrowserSession(Settings())
    session._context = FakeContext([first_page, second_page])  # type: ignore[assignment]

    page = await session.switch_to_page(1)
    tabs = await session.list_pages()

    assert page is second_page
    assert second_page.fronted is True
    assert tabs[1]["active"] is True
    assert tabs[1]["title"] == "Inbox"


@pytest.mark.asyncio
async def test_browser_session_does_not_switch_to_old_existing_tab_after_action() -> None:
    first_page = FakePage("https://mail.example/home", "Home")
    old_second_page = FakePage("https://mail.example/old", "Old")
    session = BrowserSession(Settings())
    session._context = FakeContext([first_page, old_second_page])  # type: ignore[assignment]
    session._active_page = first_page  # type: ignore[assignment]
    known_page_ids = {id(first_page), id(old_second_page)}

    page = await session.wait_for_page_after_action(
        previous_page=first_page,  # type: ignore[arg-type]
        known_page_ids=known_page_ids,
        timeout_ms=0,
    )

    assert page is first_page
    assert first_page.fronted is True
    assert old_second_page.fronted is False


@pytest.mark.asyncio
async def test_browser_session_waits_for_delayed_new_tab_after_action() -> None:
    first_page = FakePage("https://mail.example/home", "Home")
    session = BrowserSession(Settings())
    context = FakeContext([first_page])
    session._context = context  # type: ignore[assignment]
    session._active_page = first_page  # type: ignore[assignment]
    known_page_ids = {id(first_page)}

    async def open_delayed_tab() -> None:
        await asyncio.sleep(0.05)
        new_page = FakePage("https://mail.example/new", "New")
        context.pages.append(new_page)
        session._handle_new_page(new_page)  # type: ignore[arg-type]

    task = asyncio.create_task(open_delayed_tab())
    page = await session.wait_for_page_after_action(
        previous_page=first_page,  # type: ignore[arg-type]
        known_page_ids=known_page_ids,
        timeout_ms=500,
    )
    await task

    assert page.url == "https://mail.example/new"
    assert page.fronted is True
