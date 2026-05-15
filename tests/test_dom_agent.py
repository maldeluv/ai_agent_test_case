from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.config import Settings
from app.subagents.dom_agent import DOMSubAgent
from app.tools.schemas import DomCandidate


class FakeDomClient:
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


def candidate(selector: str = "input[name=\"q\"]") -> DomCandidate:
    return DomCandidate(
        tag="input",
        selector=selector,
        text="",
        aria_label="Search",
        placeholder="Search",
        name="q",
        disabled=False,
        visible=True,
        nearby_text="Search",
    )


@pytest.mark.asyncio
async def test_dom_agent_returns_strict_result_format() -> None:
    client = FakeDomClient(
        """
        {
          "found": true,
          "answer": "Search field found",
          "matches": [
            {
              "selector": "input[name=\\"q\\"]",
              "description": "Main search input",
              "confidence": 0.93
            }
          ]
        }
        """
    )
    agent = DOMSubAgent(Settings(), client=client)

    result = await agent.analyze(query="find search input", candidates=[candidate()])

    assert result.found is True
    assert result.answer == "Search field found"
    assert len(result.matches) == 1
    assert result.matches[0].selector == 'input[name="q"]'
    assert result.matches[0].confidence == 0.93


@pytest.mark.asyncio
async def test_dom_agent_filters_matches_not_present_in_candidates() -> None:
    client = FakeDomClient(
        """
        {
          "found": true,
          "answer": "Selector guessed",
          "matches": [
            {
              "selector": "#invented",
              "description": "Not from candidates",
              "confidence": 0.9
            }
          ]
        }
        """
    )
    agent = DOMSubAgent(Settings(), client=client)

    result = await agent.analyze(query="find search input", candidates=[candidate()])

    assert result.found is False
    assert result.matches == []


@pytest.mark.asyncio
async def test_dom_agent_empty_candidates_returns_empty_matches() -> None:
    agent = DOMSubAgent(Settings(), client=FakeDomClient("{}"))

    result = await agent.analyze(query="find search input", candidates=[])

    assert result.found is False
    assert result.matches == []


@pytest.mark.asyncio
async def test_dom_agent_limits_candidate_payload_size() -> None:
    client = FakeDomClient(
        """
        {
          "found": false,
          "answer": "No match",
          "matches": []
        }
        """
    )
    settings = Settings(dom_query_payload_max_chars=1200, dom_max_text_chars=40)
    candidates = [
        DomCandidate(
            tag="button",
            selector=f"button:nth-of-type({index + 1})",
            text="x" * 500,
            disabled=False,
            visible=True,
            nearby_text="y" * 500,
        )
        for index in range(20)
    ]
    agent = DOMSubAgent(settings, client=client)

    await agent.analyze(query="find button", candidates=candidates)

    payload = client.calls[0]["messages"][0]["content"]
    assert len(payload) <= settings.dom_query_payload_max_chars
    assert "x" * 100 not in payload
