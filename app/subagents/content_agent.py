from __future__ import annotations

import json
from typing import Any, Protocol

from app.config import Settings
from app.llm.client import create_llm_client
from app.llm.tool_use import get_block_text, get_block_type
from app.tools.schemas import ContentItemAnalysis, ContentQueryData, VisibleItem
from app.utils.truncate import json_char_size, truncate_text, truncate_value


CONTENT_SUB_AGENT_SYSTEM_PROMPT = """You are a page content analyst for a browser automation agent.

You receive a user-facing query and a compact list of visible content items
extracted from the current browser viewport. Items may be email rows, table
rows, product cards, search results, notifications, or other repeated page
entities. Your job is to interpret the provided items only.

Rules:
- Return strict JSON only. No markdown, no code fences, no commentary.
- Use only item indexes that exist in the provided items list.
- Do not invent hidden page content, selectors, senders, subjects, or controls.
- Prefer concise structured fields over long prose.
- For email-like items, put sender, subject, and snippet in fields when visible.
- If asked to classify spam or risky content, give classification, reason,
  recommended_action, and confidence for each relevant item.
- If visible snippets are insufficient for a confident classification, say so in
  reason and lower confidence.
- If no relevant item is present, return found=false and items=[].

Required JSON shape:
{
  "found": true,
  "answer": "short answer",
  "items": [
    {
      "index": 1,
      "item_type": "email | row | card | notification | unknown",
      "fields": {
        "sender": "visible sender if present",
        "subject": "visible subject if present",
        "snippet": "visible snippet if present"
      },
      "summary": "short item summary",
      "classification": "spam | important | normal | suspicious | unknown",
      "reason": "why this classification or why uncertain",
      "recommended_action": "keep | delete_or_mark_spam | open_for_more_detail | none",
      "confidence": 0.0
    }
  ]
}
"""


class ContentAgentClient(Protocol):
    async def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        pass


class ContentSubAgent:
    def __init__(
        self,
        settings: Settings,
        client: ContentAgentClient | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or create_llm_client(settings)

    async def analyze(
        self,
        *,
        query: str,
        items: list[VisibleItem],
    ) -> ContentQueryData:
        if not items:
            return ContentQueryData(
                found=False,
                answer="No visible repeated content items were found.",
                items=[],
            )

        content = self._build_payload(query=query, items=items)
        response = await self.client.create_message(
            system=CONTENT_SUB_AGENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            tools=[],
        )
        text = self._response_text(response)
        parsed = ContentQueryData.model_validate_json(self._extract_json_object(text))
        return self._attach_source_items(parsed, items)

    def _build_payload(self, *, query: str, items: list[VisibleItem]) -> str:
        compact_query = truncate_text(query, max_chars=1000)
        payload_items: list[dict[str, Any]] = []
        for item in items:
            compact_item = truncate_value(
                item.model_dump(mode="json", exclude_none=True),
                max_string_chars=self.settings.content_max_text_chars,
                max_list_items=self.settings.content_max_controls_per_item,
                max_depth=4,
            )
            tentative = {
                "query": compact_query,
                "items": [*payload_items, compact_item],
            }
            if payload_items and json_char_size(tentative) > self.settings.content_query_payload_max_chars:
                break
            payload_items.append(compact_item)

        payload = {
            "query": compact_query,
            "items": payload_items,
        }
        payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
        if len(payload_text) <= self.settings.content_query_payload_max_chars:
            return payload_text

        fallback_payload = {
            "query": truncate_text(compact_query, max_chars=300),
            "items": payload_items[:1],
            "payload_truncated": True,
        }
        fallback_text = json.dumps(fallback_payload, ensure_ascii=False, indent=2)
        if len(fallback_text) <= self.settings.content_query_payload_max_chars:
            return fallback_text
        return json.dumps(
            {
                "query": truncate_text(compact_query, max_chars=300),
                "items": [],
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
            raise ValueError("Content Sub-Agent did not return a JSON object")
        return stripped[start : end + 1]

    def _attach_source_items(
        self,
        result: ContentQueryData,
        source_items: list[VisibleItem],
    ) -> ContentQueryData:
        source_by_index = {item.index: item for item in source_items}
        attached: list[ContentItemAnalysis] = []

        for item in result.items:
            source_item = source_by_index.get(item.index)
            if source_item is None:
                continue
            attached.append(
                ContentItemAnalysis(
                    index=item.index,
                    selector=item.selector or source_item.selector,
                    item_type=item.item_type,
                    fields=item.fields,
                    summary=item.summary,
                    classification=item.classification,
                    reason=item.reason,
                    recommended_action=item.recommended_action,
                    confidence=item.confidence,
                    scroll_container_selector=source_item.scroll_container_selector,
                    controls=source_item.controls,
                )
            )

        if not attached:
            return ContentQueryData(
                found=False,
                answer=result.answer if result.answer else "No matching visible item found.",
                items=[],
            )
        return ContentQueryData(
            found=result.found,
            answer=result.answer,
            items=attached,
        )
