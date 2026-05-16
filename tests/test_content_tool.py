from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from app.config import Settings
from app.safety import SafetyGuard
from app.tools.content import (
    classify_items_with_evidence,
    collect_visible_items,
    extract_visible_items,
    prepare_batch_action_confirmation,
)
from app.tools.registry import ToolContext, create_default_tool_registry
from app.tools.schemas import (
    ClassifyItemsWithEvidenceInput,
    ContentItemAnalysis,
    ContentQueryData,
    ExtractVisibleItemsInput,
    PrepareBatchActionConfirmationInput,
    VisibleItem,
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


class PlaywrightBrowser:
    def __init__(self, page: object) -> None:
        self.settings = Settings(
            content_max_items=20,
            content_max_text_chars=200,
            content_max_controls_per_item=2,
        )
        self.page = page

    async def get_active_page(self) -> object:
        return self.page

    async def list_pages(self) -> list[dict[str, object]]:
        return [
            {
                "index": 0,
                "active": True,
                "url": getattr(self.page, "url", ""),
                "title": await self.page.title(),
            }
        ]


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


class ClassifyAllSpamSubAgent:
    def __init__(self, _: Settings) -> None:
        pass

    async def analyze(self, **kwargs: object) -> ContentQueryData:
        items = kwargs["items"]
        assert isinstance(items, list)
        analyses = []
        for item in items:
            assert isinstance(item, VisibleItem)
            source_text = item.source_text or item.text
            if "Promo" not in source_text:
                continue
            analyses.append(
                ContentItemAnalysis(
                    index=item.index,
                    selector=item.selector,
                    item_type="email",
                    fields={
                        "sender": "Promo Shop",
                        "subject": "Huge sale today",
                        "snippet": "Limited offer unsubscribe",
                    },
                    summary="Promotional email",
                    classification="spam",
                    reason="Visible promotional terms",
                    recommended_action="delete_or_mark_spam",
                    confidence=0.92,
                    source_text=source_text,
                    controls=item.controls,
                )
            )
        return ContentQueryData(
            found=bool(analyses),
            answer=f"{len(analyses)} spam item(s)",
            items=analyses,
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


@pytest.mark.asyncio
async def test_collect_visible_items_gets_10_items_across_inner_scroll() -> None:
    rows = "\n".join(
        f"""
        <div id="mail-{index}" role="listitem" class="row">
          <input type="checkbox" aria-label="Select email {index}">
          <span>Sender {index}</span>
          <span>Subject {index}</span>
          <span>Snippet {index}</span>
        </div>
        """
        for index in range(1, 13)
    )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 800, "height": 600})
        await page.set_content(
            f"""
            <div id="inbox" role="list">{rows}</div>
            <style>
              #inbox {{
                width: 640px;
                height: 150px;
                overflow-y: auto;
              }}
              .row {{
                height: 44px;
                display: grid;
                grid-template-columns: 32px 120px 160px 1fr;
                align-items: center;
              }}
            </style>
            """
        )

        result = await collect_visible_items(
            {
                "query": "email rows sender subject snippet",
                "target_count": 10,
                "max_scroll_steps": 8,
                "scroll_amount": 132,
                "container_selector": "#inbox",
            },
            ToolContext(browser=PlaywrightBrowser(page)),  # type: ignore[arg-type]
        )
        await browser.close()

    assert result.ok is True
    assert result.data["collected_count"] == 10
    assert result.data["reached_target"] is True
    texts = [item["source_text"] for item in result.data["items"]]
    assert len(set(texts)) == 10


@pytest.mark.asyncio
async def test_prepare_batch_action_confirmation_builds_click_args() -> None:
    item = ContentItemAnalysis(
        index=1,
        selector="#mail-1",
        item_type="email",
        fields={
            "sender": "Promo Shop",
            "subject": "Huge sale today",
            "snippet": "Limited offer unsubscribe",
        },
        summary="Promotional email",
        classification="spam",
        reason="Visible promotional terms",
        recommended_action="delete_or_mark_spam",
        confidence=0.91,
        source_text="Promo Shop Huge sale today Limited offer unsubscribe",
        controls=[
            VisibleItemControl(
                kind="checkbox",
                selector="#mail-1 input[type='checkbox']",
            )
        ],
    )

    result = await prepare_batch_action_confirmation(
        PrepareBatchActionConfirmationInput(
            action="delete",
            action_selector="#delete-selected",
            items=[item],
            min_confidence=0.5,
        ),
        ToolContext(browser=FakeBrowser()),  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert result.data["click_element_args"]["selector"] == "#delete-selected"
    assert result.data["batch_items"][0]["selector"] == "#mail-1"
    assert result.data["batch_items"][0]["control_selector"] == "#mail-1 input[type='checkbox']"
    assert result.data["batch_items"][0]["evidence_signature"]


@pytest.mark.asyncio
async def test_classify_items_with_evidence_uses_local_spam_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class UnknownSubAgent:
        def __init__(self, _: Settings) -> None:
            pass

        async def analyze(self, **kwargs: object) -> ContentQueryData:
            items = kwargs["items"]
            assert isinstance(items, list)
            source_item = items[0]
            assert isinstance(source_item, VisibleItem)
            return ContentQueryData(
                found=True,
                answer="Unknown",
                items=[
                    ContentItemAnalysis(
                        index=1,
                        selector=source_item.selector,
                        item_type="email",
                        fields={},
                        summary="Unknown item",
                        classification="unknown",
                        reason="Not enough model confidence",
                        recommended_action="none",
                        confidence=0.2,
                        source_text=source_item.source_text or source_item.text,
                        controls=source_item.controls,
                    )
                ],
            )

    monkeypatch.setattr("app.tools.content.ContentSubAgent", UnknownSubAgent)
    visible_item = VisibleItem(
        index=1,
        selector="#mail-1",
        tag="div",
        role="listitem",
        text="Promo Shop Huge sale today Limited offer unsubscribe",
        source_text="Promo Shop Huge sale today Limited offer unsubscribe",
    )

    result = await classify_items_with_evidence(
        ClassifyItemsWithEvidenceInput(query="classify spam", items=[visible_item]),
        ToolContext(browser=FakeBrowser()),  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert result.data["items"][0]["classification"] == "spam"
    assert result.data["items"][0]["recommended_action"] == "delete_or_mark_spam"


@pytest.mark.asyncio
async def test_fake_mail_batch_delete_requires_confirmation_and_removes_confirmed_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.tools.content.ContentSubAgent", ClassifyAllSpamSubAgent)
    rows = """
      <div id="mail-1" role="listitem" class="row">
        <input type="checkbox" aria-label="Select email 1">
        <span>Promo Shop</span><span>Huge sale today</span><span>Limited offer unsubscribe</span>
      </div>
      <div id="mail-2" role="listitem" class="row">
        <input type="checkbox" aria-label="Select email 2">
        <span>Important Sender</span><span>Project update</span><span>Useful work details</span>
      </div>
    """

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 900, "height": 600})
        await page.set_content(
            f"""
            <button
              id="delete-selected"
              onclick="document.querySelectorAll('.row input:checked').forEach((box) => box.closest('.row').remove())"
            >
              Delete selected
            </button>
            <div id="inbox" role="list">{rows}</div>
            <style>
              .row {{ height: 44px; width: 760px; display: grid; grid-template-columns: 32px 160px 180px 1fr; }}
            </style>
            """
        )
        test_browser = PlaywrightBrowser(page)
        guard = SafetyGuard(confirmation_callback=lambda *_: True)
        context = ToolContext(browser=test_browser, safety_guard=guard)  # type: ignore[arg-type]
        registry = create_default_tool_registry()

        collected = await registry.execute(
            "collect_visible_items",
            {"query": "email rows", "target_count": 2, "max_scroll_steps": 0},
            context,
        )
        classified = await registry.execute(
            "classify_items_with_evidence",
            {"query": "classify spam", "items": collected.data["items"]},
            context,
        )
        prepared = await registry.execute(
            "prepare_batch_action_confirmation",
            {
                "action": "delete",
                "action_selector": "#delete-selected",
                "items": classified.data["items"],
                "min_confidence": 0.5,
            },
            context,
        )
        checkbox_selector = prepared.data["batch_items"][0]["control_selector"]
        select_result = await registry.execute(
            "click_element",
            {"selector": checkbox_selector, "action_description": "Select email row"},
            context,
        )
        blocked = await registry.execute(
            "click_element",
            prepared.data["click_element_args"],
            context,
        )
        confirmation = await registry.execute(
            "ask_user_confirmation",
            {
                **prepared.data["ask_user_confirmation_args"],
                "approval_id": blocked.data["approval_id"],
            },
            context,
        )
        deleted = await registry.execute(
            "click_element",
            prepared.data["click_element_args"],
            context,
        )
        remaining_rows = await page.locator(".row").count()
        promo_exists = await page.locator("#mail-1").count()
        await browser.close()

    assert collected.ok is True
    assert classified.ok is True
    assert prepared.ok is True
    assert select_result.ok is True
    assert blocked.ok is False
    assert blocked.error_code == "safety_confirmation_required"
    assert confirmation.ok is True
    assert deleted.ok is True
    assert remaining_rows == 1
    assert promo_exists == 0
