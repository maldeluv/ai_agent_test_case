from __future__ import annotations

import json
from typing import Any, Protocol

from app.config import Settings
from app.llm.client import create_llm_client
from app.llm.tool_use import get_block_text, get_block_type
from app.tools.schemas import DomCandidate, DomMatch, DomQueryData


DOM_SUB_AGENT_SYSTEM_PROMPT = """You are a DOM analyst for a browser automation agent.

You receive a user-facing query and a compact list of DOM candidates extracted
from the current page. Your job is to identify the most relevant element or
elements from the provided candidates only.

Rules:
- Return strict JSON only. No markdown, no code fences, no extra commentary.
- Use only selectors that exist in the provided candidates list.
- Do not invent selectors, URLs, labels, or page elements.
- If no candidate is a good match, return found=false and matches=[].
- If confidence is low, still be honest in answer and confidence.

Required JSON shape:
{
  "found": true,
  "answer": "short answer",
  "matches": [
    {
      "selector": "selector from candidates",
      "description": "why this element matches",
      "confidence": 0.0
    }
  ]
}
"""


class DomAgentClient(Protocol):
    async def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        pass


class DOMSubAgent:
    def __init__(
        self,
        settings: Settings,
        client: DomAgentClient | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or create_llm_client(settings)

    async def analyze(
        self,
        *,
        query: str,
        candidates: list[DomCandidate],
    ) -> DomQueryData:
        if not candidates:
            return DomQueryData(
                found=False,
                answer="No visible interactive DOM candidates were found.",
                matches=[],
            )

        candidate_payload = [
            candidate.model_dump(mode="json", exclude_none=True)
            for candidate in candidates
        ]
        content = json.dumps(
            {
                "query": query,
                "candidates": candidate_payload,
            },
            ensure_ascii=False,
            indent=2,
        )
        response = await self.client.create_message(
            system=DOM_SUB_AGENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            tools=[],
        )
        text = self._response_text(response)
        parsed = DomQueryData.model_validate_json(self._extract_json_object(text))
        return self._filter_to_candidate_selectors(parsed, candidates)

    def _response_text(self, response: Any) -> str:
        chunks: list[str] = []
        for block in getattr(response, "content", []):
            if get_block_type(block) == "text":
                chunks.append(get_block_text(block))
        return "\n".join(chunks).strip()

    def _extract_json_object(self, text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("DOM Sub-Agent did not return a JSON object")
        return stripped[start : end + 1]

    def _filter_to_candidate_selectors(
        self,
        result: DomQueryData,
        candidates: list[DomCandidate],
    ) -> DomQueryData:
        allowed_selectors = {candidate.selector for candidate in candidates}
        matches = [
            DomMatch(
                selector=match.selector,
                description=match.description,
                confidence=match.confidence,
            )
            for match in result.matches
            if match.selector in allowed_selectors
        ]
        if not matches:
            return DomQueryData(
                found=False,
                answer=result.answer if result.answer else "No matching element found.",
                matches=[],
            )
        return DomQueryData(
            found=result.found,
            answer=result.answer,
            matches=matches,
        )
