from __future__ import annotations

import pytest

from app.config import Settings
from app.tools.dom_query import query_dom
from app.tools.registry import ToolContext
from app.tools.schemas import DomQueryData, DomMatch, QueryDomInput


class FakePage:
    def __init__(self, candidates: list[dict[str, object]]) -> None:
        self.candidates = candidates

    async def evaluate(self, *_: object) -> list[dict[str, object]]:
        return self.candidates


class FakeBrowser:
    def __init__(self, candidates: list[dict[str, object]]) -> None:
        self.settings = Settings(openai_api_key="sk-test")
        self.page = FakePage(candidates)

    async def get_active_page(self) -> FakePage:
        return self.page


class FakeDOMSubAgent:
    def __init__(self, _: Settings) -> None:
        pass

    async def analyze(self, **_: object) -> DomQueryData:
        return DomQueryData(
            found=True,
            answer="Found search field",
            matches=[
                DomMatch(
                    selector='input[name="q"]',
                    description="Search input",
                    confidence=0.91,
                )
            ],
        )


@pytest.mark.asyncio
async def test_query_dom_returns_expected_result_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.tools.dom_query.DOMSubAgent", FakeDOMSubAgent)
    browser = FakeBrowser(
        [
            {
                "tag": "input",
                "selector": 'input[name="q"]',
                "text": "",
                "aria_label": "Search",
                "placeholder": "Search",
                "name": "q",
                "disabled": False,
                "visible": True,
                "nearby_text": "Search",
            }
        ]
    )

    result = await query_dom(
        QueryDomInput(query="find search field"),
        ToolContext(browser=browser),  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert result.data["found"] is True
    assert result.data["answer"] == "Found search field"
    assert result.data["candidate_count"] == 1
    assert result.data["matches"] == [
        {
            "selector": 'input[name="q"]',
            "description": "Search input",
            "confidence": 0.91,
        }
    ]


@pytest.mark.asyncio
async def test_query_dom_empty_candidates_returns_empty_matches() -> None:
    browser = FakeBrowser([])

    result = await query_dom(
        QueryDomInput(query="find search field"),
        ToolContext(browser=browser),  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert result.data["found"] is False
    assert result.data["matches"] == []
    assert result.data["candidate_count"] == 0
