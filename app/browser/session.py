from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from app.config import Settings
from app.utils.logger import get_logger


class BrowserSession:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.profile_dir = Path(settings.browser_profile_dir)
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._active_page: Page | None = None
        self._tracked_page_ids: set[int] = set()
        self._logger = get_logger(__name__)

    @property
    def is_started(self) -> bool:
        return self._context is not None

    async def start(self) -> Page:
        if self._context is not None:
            return await self.get_active_page()

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._logger.info(
            "Starting Chromium with persistent profile: %s",
            self.profile_dir,
        )

        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=False,
            viewport={
                "width": self.settings.viewport_width,
                "height": self.settings.viewport_height,
            },
        )
        self._context.on("page", self._handle_new_page)
        for page in self._context.pages:
            self._track_page(page)

        open_pages = self._open_pages()
        self._active_page = self._choose_default_page(open_pages)
        if self._active_page is None:
            self._active_page = await self._context.new_page()
        await self._active_page.bring_to_front()
        return self._active_page

    async def get_active_page(self) -> Page:
        if self._context is None:
            raise RuntimeError("Browser session is not started")

        if self._active_page is not None and not self._active_page.is_closed():
            self._track_page(self._active_page)
            await self._active_page.bring_to_front()
            return self._active_page

        open_pages = self._open_pages()
        self._active_page = self._choose_default_page(open_pages)
        if self._active_page is None:
            self._active_page = await self._context.new_page()
        await self._active_page.bring_to_front()
        return self._active_page

    async def wait_for_page_after_action(
        self,
        *,
        previous_page: Page,
        known_page_ids: set[int] | None = None,
        timeout_ms: int,
    ) -> Page:
        known_page_ids = known_page_ids or {id(previous_page)}
        deadline = asyncio.get_running_loop().time() + max(timeout_ms, 0) / 1000
        while asyncio.get_running_loop().time() < deadline:
            active_page = self._active_page
            if (
                active_page is not None
                and active_page is not previous_page
                and id(active_page) not in known_page_ids
                and not active_page.is_closed()
            ):
                await active_page.bring_to_front()
                return active_page

            open_pages = self._open_pages()
            new_pages = [page for page in open_pages if id(page) not in known_page_ids]
            if new_pages:
                self._active_page = new_pages[-1]
                await self._active_page.bring_to_front()
                return self._active_page

            await asyncio.sleep(0.05)

        return await self.get_active_page()

    def page_ids(self) -> set[int]:
        return {id(page) for page in self._open_pages()}

    async def list_pages(self) -> list[dict[str, Any]]:
        if self._context is None:
            raise RuntimeError("Browser session is not started")

        active_page = await self.get_active_page()
        tabs: list[dict[str, Any]] = []
        for index, page in enumerate(self._open_pages()):
            tabs.append(
                {
                    "index": index,
                    "active": page is active_page,
                    "url": page.url,
                    "title": await self._safe_title(page),
                }
            )
        return tabs

    async def switch_to_page(self, index: int) -> Page:
        if self._context is None:
            raise RuntimeError("Browser session is not started")

        open_pages = self._open_pages()
        if index < 0 or index >= len(open_pages):
            raise IndexError(f"tab index out of range: {index}")

        self._active_page = open_pages[index]
        await self._active_page.bring_to_front()
        return self._active_page

    async def close(self) -> None:
        context = self._context
        playwright = self._playwright

        self._context = None
        self._playwright = None
        self._active_page = None
        self._tracked_page_ids.clear()

        if context is not None:
            await context.close()
        if playwright is not None:
            await playwright.stop()

    def _handle_new_page(self, page: Page) -> None:
        self._track_page(page)
        self._active_page = page
        self._logger.info("New browser tab detected: %s", page.url)

    def _track_page(self, page: Page) -> None:
        page_id = id(page)
        if page_id in self._tracked_page_ids:
            return
        self._tracked_page_ids.add(page_id)
        page.on("close", lambda: self._handle_page_closed(page))

    def _handle_page_closed(self, page: Page) -> None:
        self._tracked_page_ids.discard(id(page))
        if self._active_page is page:
            self._active_page = None

    def _open_pages(self) -> list[Page]:
        if self._context is None:
            return []
        pages = []
        for page in self._context.pages:
            if not page.is_closed():
                self._track_page(page)
                pages.append(page)
        return pages

    def _choose_default_page(self, pages: list[Page]) -> Page | None:
        if not pages:
            return None
        for page in reversed(pages):
            if page.url and page.url != "about:blank":
                return page
        return pages[-1]

    async def _safe_title(self, page: Page) -> str:
        try:
            return await page.title()
        except Exception:
            return ""
