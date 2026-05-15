from __future__ import annotations

import pytest

from app.config import Settings
from app.tools.observations import get_current_page_info
from app.tools.registry import ToolContext
from app.tools.schemas import EmptyInput


class FakeBodyLocator:
    async def inner_text(self, **_: object) -> str:
        return "visible text " * 100


class FakeInfoPage:
    url = "https://example.test"

    async def title(self) -> str:
        return "Example"

    def locator(self, selector: str) -> FakeBodyLocator:
        assert selector == "body"
        return FakeBodyLocator()


class FakeInfoBrowser:
    def __init__(self) -> None:
        self.settings = Settings(short_visible_text_chars=200)
        self.page = FakeInfoPage()

    async def get_active_page(self) -> FakeInfoPage:
        return self.page


@pytest.mark.asyncio
async def test_current_page_info_truncates_visible_text() -> None:
    result = await get_current_page_info(
        EmptyInput(),
        ToolContext(browser=FakeInfoBrowser()),  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert len(result.data["short_visible_text"]) <= 200
    assert result.data["short_visible_text"].endswith("...")
