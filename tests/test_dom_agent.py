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

    async def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
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
