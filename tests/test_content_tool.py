from __future__ import annotations

import pytest

from app.config import Settings
from app.tools.content import extract_visible_items
from app.tools.registry import ToolContext
from app.tools.schemas import (
    ContentItemAnalysis,
    ContentQueryData,
    ExtractVisibleItemsInput,
    VisibleItemControl,
)


class FakePage:
    async def evaluate(self, *_: object) -> list[dict[str, object]]:
        return [
            {
                "index": 1,
                "selector": "#mail-1",
                "tag": "div",
                "role": "listitem",
                "text": "Promo Shop Huge sale today",
                "source_kind": "semantic_item",
                "width": 900,
                "height": 42,
                "controls": [
                    {
                        "kind": "checkbox",
                        "selector": "#mail-1 input",
                        "aria_label": "Select email 1",
                        "disabled": False,
                    }
                ],
            }
        ]


class FakeBrowser:
    def __init__(self) -> None:
        self.settings = Settings(openai_api_key="sk-test")
        self.page = FakePage()

    async def get_active_page(self) -> FakePage:
        return self.page


class FakeContentSubAgent:
    def __init__(self, _: Settings) -> None:
        pass

    async def analyze(self, **_: object) -> ContentQueryData:
        return ContentQueryData(
            found=True,
            answer="Spam candidate found",
            items=[
                ContentItemAnalysis(
                    index=1,
                    selector="#mail-1",
                    item_type="email",
                    fields={
                        "sender": "Promo Shop",
                        "subject": "Huge sale today",
                        "snippet": "Promo",
                    },
                    summary="Promotional email",
                    classification="spam",
                    reason="Promotional content",
                    recommended_action="delete_or_mark_spam",
                    confidence=0.9,
                    controls=[
                        VisibleItemControl(
                            kind="checkbox",
                            selector="#mail-1 input",
                            aria_label="Select email 1",
                        )
                    ],
                )
            ],
        )


@pytest.mark.asyncio
async def test_extract_visible_items_tool_returns_structured_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.tools.content.ContentSubAgent", FakeContentSubAgent)

    result = await extract_visible_items(
        ExtractVisibleItemsInput(query="read inbox spam", max_items=10),
        ToolContext(browser=FakeBrowser()),  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert result.data["found"] is True
    assert result.data["raw_item_count"] == 1
    assert result.data["items"][0]["fields"]["sender"] == "Promo Shop"
    assert result.data["items"][0]["controls"][0]["selector"] == "#mail-1 input"
