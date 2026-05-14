from __future__ import annotations

from pathlib import Path

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

        self._active_page = (
            self._context.pages[0]
            if self._context.pages
            else await self._context.new_page()
        )
        await self._active_page.bring_to_front()
        return self._active_page

    async def get_active_page(self) -> Page:
        if self._context is None:
            raise RuntimeError("Browser session is not started")

        if self._active_page is not None and not self._active_page.is_closed():
            return self._active_page

        open_pages = [page for page in self._context.pages if not page.is_closed()]
        self._active_page = open_pages[-1] if open_pages else await self._context.new_page()
        await self._active_page.bring_to_front()
        return self._active_page

    async def close(self) -> None:
        context = self._context
        playwright = self._playwright

        self._context = None
        self._playwright = None
        self._active_page = None

        if context is not None:
            await context.close()
        if playwright is not None:
            await playwright.stop()
