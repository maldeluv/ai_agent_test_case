from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.config import Settings
from app.subagents.content_agent import ContentSubAgent
from app.tools.schemas import VisibleItem, VisibleItemControl


class FakeContentClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    async def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        return SimpleNamespace(content=[{"type": "text", "text": self.text}])


class SequenceContentClient:
    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.calls: list[dict[str, Any]] = []

    async def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        index = min(len(self.calls) - 1, len(self.texts) - 1)
        return SimpleNamespace(content=[{"type": "text", "text": self.texts[index]}])


def visible_email(index: int = 1) -> VisibleItem:
    return VisibleItem(
        index=index,
        selector=f"#mail-{index}",
        tag="div",
        role="listitem",
        text="Promo Shop Huge sale today Limited offer unsubscribe",
        source_kind="semantic_item",
        width=900,
        height=42,
        controls=[
            VisibleItemControl(
                kind="checkbox",
                selector=f"#mail-{index} input[type=\"checkbox\"]",
                aria_label=f"Select email {index}",
            )
        ],
    )


@pytest.mark.asyncio
async def test_content_agent_returns_email_classification_and_attaches_controls() -> None:
    client = FakeContentClient(
        """
        {
          "found": true,
          "answer": "One likely spam email found.",
          "items": [
            {
              "index": 1,
              "item_type": "email",
              "fields": {
                "sender": "Promo Shop",
                "subject": "Huge sale today",
                "snippet": "Limited offer unsubscribe"
              },
              "summary": "Promotional sale email",
              "classification": "spam",
              "reason": "Promotional language and unsubscribe hint",
              "recommended_action": "delete_or_mark_spam",
              "confidence": 0.88
            }
          ]
        }
        """
    )
    agent = ContentSubAgent(Settings(), client=client)

    result = await agent.analyze(query="classify inbox spam", items=[visible_email()])

    assert result.found is True
    assert result.items[0].selector == "#mail-1"
    assert result.items[0].fields["sender"] == "Promo Shop"
    assert result.items[0].classification == "spam"
    assert result.items[0].controls[0].kind == "checkbox"


@pytest.mark.asyncio
async def test_content_agent_filters_indexes_not_present_in_items() -> None:
    client = FakeContentClient(
        """
        {
          "found": true,
          "answer": "Invented item index",
          "items": [
            {
              "index": 99,
              "item_type": "email",
              "fields": {},
              "summary": "Not visible",
              "classification": "spam",
              "reason": "Not allowed",
              "recommended_action": "delete_or_mark_spam",
              "confidence": 0.9
            }
          ]
        }
        """
    )
    agent = ContentSubAgent(Settings(), client=client)

    result = await agent.analyze(query="classify spam", items=[visible_email()])

    assert result.found is False
    assert result.items == []


@pytest.mark.asyncio
async def test_content_agent_limits_payload_size() -> None:
    client = FakeContentClient(
        """
        {
          "found": false,
          "answer": "No relevant items",
          "items": []
        }
        """
    )
    settings = Settings(
        content_query_payload_max_chars=2000,
        content_max_text_chars=80,
        content_max_controls_per_item=2,
    )
    items = [
        VisibleItem(
            index=index + 1,
            selector=f"#row-{index + 1}",
            tag="div",
            text="x" * 1000,
            source_kind="repeated_sibling",
            width=900,
            height=48,
        )
        for index in range(20)
    ]
    agent = ContentSubAgent(settings, client=client)

    await agent.analyze(query="read rows", items=items)

    payload = client.calls[0]["messages"][0]["content"]
    assert len(payload) <= settings.content_query_payload_max_chars
    assert "x" * 200 not in payload


@pytest.mark.asyncio
async def test_content_agent_repairs_malformed_json_once() -> None:
    client = SequenceContentClient(
        [
            "not json",
            """
            {
              "found": true,
              "answer": "One likely spam email found.",
              "items": [
                {
                  "index": 1,
                  "item_type": "email",
                  "fields": {"sender": "Promo Shop"},
                  "summary": "Promotional sale email",
                  "classification": "spam",
                  "reason": "Promotional language",
                  "recommended_action": "delete_or_mark_spam",
                  "confidence": 0.8
                }
              ]
            }
            """,
        ]
    )
    agent = ContentSubAgent(Settings(), client=client)

    result = await agent.analyze(query="classify inbox spam", items=[visible_email()])

    assert result.found is True
    assert result.items[0].fields["sender"] == "Promo Shop"
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_content_agent_discards_invented_selector_and_unsupported_fields() -> None:
    client = FakeContentClient(
        """
        {
          "found": true,
          "answer": "Invented details",
          "items": [
            {
              "index": 1,
              "selector": "#invented",
              "item_type": "email",
              "fields": {
                "sender": "Imaginary Sender",
                "subject": "Huge sale today"
              },
              "summary": "Promotional sale email",
              "classification": "spam",
              "reason": "Promotional language",
              "recommended_action": "delete_or_mark_spam",
              "confidence": 0.92
            }
          ]
        }
        """
    )
    agent = ContentSubAgent(Settings(), client=client)

    result = await agent.analyze(query="classify inbox spam", items=[visible_email()])

    assert result.found is True
    assert result.items[0].selector == "#mail-1"
    assert "sender" not in result.items[0].fields
    assert result.items[0].fields["subject"] == "Huge sale today"
    assert result.items[0].confidence <= 0.35


@pytest.mark.asyncio
async def test_content_agent_returns_structured_failure_after_bad_repair() -> None:
    client = SequenceContentClient(["not json", "still not json"])
    agent = ContentSubAgent(Settings(), client=client)

    result = await agent.analyze(query="classify inbox spam", items=[visible_email()])

    assert result.found is False
    assert result.error_code == "invalid_subagent_json"
    assert result.raw_preview
