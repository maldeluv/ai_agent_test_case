from __future__ import annotations

import json
from typing import Any, Protocol

from app.config import Settings
from app.llm.client import create_llm_client
from app.llm.tool_use import get_block_text, get_block_type
from app.tools.schemas import DomCandidate, DomMatch, DomQueryData
from app.utils.truncate import json_char_size, truncate_text, truncate_value


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

        content = self._build_payload(query=query, candidates=candidates)
        parsed = await self._request_json_with_repair(content)
        if parsed.error_code:
            return parsed
        return self._filter_to_candidate_selectors(parsed, candidates)

    async def _request_json_with_repair(self, content: str) -> DomQueryData:
        raw_text = ""
        last_error: Exception | None = None
        messages = [{"role": "user", "content": content}]
        for attempt in range(2):
            response = await self.client.create_message(
                system=DOM_SUB_AGENT_SYSTEM_PROMPT,
                messages=messages,
                tools=[],
            )
            raw_text = self._response_text(response)
            try:
                return DomQueryData.model_validate_json(
                    self._extract_json_object(raw_text)
                )
            except Exception as exc:
                last_error = exc
                messages = [
                    {"role": "user", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "The previous response was not valid strict JSON for the "
                            "required schema. Repair it now. Return only one JSON object. "
                            f"Parser error: {type(exc).__name__}: {exc}. "
                            f"Invalid response preview: {truncate_text(raw_text, max_chars=800)}"
                        ),
                    },
                ]

        return DomQueryData(
            found=False,
            answer="DOM Sub-Agent returned invalid JSON after retry.",
            matches=[],
            error_code="invalid_subagent_json",
            raw_preview=truncate_text(raw_text or str(last_error), max_chars=1000),
        )

    def _build_payload(self, *, query: str, candidates: list[DomCandidate]) -> str:
        compact_query = truncate_text(query, max_chars=1000)
        payload_candidates: list[dict[str, Any]] = []
        for candidate in candidates:
            compact_candidate = truncate_value(
                candidate.model_dump(mode="json", exclude_none=True),
                max_string_chars=self.settings.dom_max_text_chars,
                max_list_items=10,
                max_depth=3,
            )
            tentative = {
                "query": compact_query,
                "candidates": [*payload_candidates, compact_candidate],
            }
            if payload_candidates and json_char_size(tentative) > self.settings.dom_query_payload_max_chars:
                break
            payload_candidates.append(compact_candidate)

        payload = {
            "query": compact_query,
            "candidates": payload_candidates,
        }
        payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
        if len(payload_text) <= self.settings.dom_query_payload_max_chars:
            return payload_text
        fallback_payload = {
            "query": truncate_text(compact_query, max_chars=300),
            "candidates": payload_candidates[:1],
            "payload_truncated": True,
        }
        fallback_text = json.dumps(fallback_payload, ensure_ascii=False, indent=2)
        if len(fallback_text) <= self.settings.dom_query_payload_max_chars:
            return fallback_text
        return json.dumps(
            {
                "query": truncate_text(compact_query, max_chars=300),
                "candidates": [],
                "payload_truncated": True,
            },
            ensure_ascii=False,
        )

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
                error_code=result.error_code,
                raw_preview=result.raw_preview,
            )
        return DomQueryData(
            found=result.found,
            answer=result.answer,
            matches=matches,
            error_code=result.error_code,
            raw_preview=result.raw_preview,
        )
