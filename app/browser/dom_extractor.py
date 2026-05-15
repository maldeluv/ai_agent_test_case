from __future__ import annotations

import json
from typing import Any

from playwright.async_api import Page

from app.browser.selector_builder import SelectorBuilder
from app.config import Settings
from app.tools.schemas import DomCandidate


DOM_EXTRACTOR_JS = (
    SelectorBuilder.script()
    + r"""
function compactText(value, maxChars) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= maxChars) {
    return text;
  }
  return `${text.slice(0, maxChars).trim()}...`;
}

function isVisible(element) {
  const style = window.getComputedStyle(element);
  if (
    style.display === "none" ||
    style.visibility === "hidden" ||
    Number(style.opacity) === 0
  ) {
    return false;
  }
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

function nearbyText(element, maxChars) {
  const parent = element.closest("form, section, article, main, div, li, td, th") ||
    element.parentElement;
  if (!parent) {
    return "";
  }
  return compactText(parent.innerText || parent.textContent || "", maxChars);
}

function candidateFromElement(element, maxTextChars) {
  const tag = element.tagName.toLowerCase();
  const selector = buildSelector(element);
  const text =
    tag === "input" || tag === "textarea"
      ? element.value || element.getAttribute("value") || ""
      : element.innerText || element.textContent || "";

  return {
    tag,
    selector,
    text: compactText(text, maxTextChars),
    aria_label: element.getAttribute("aria-label"),
    placeholder: element.getAttribute("placeholder"),
    name: element.getAttribute("name"),
    title: element.getAttribute("title"),
    id: element.getAttribute("id"),
    role: element.getAttribute("role"),
    disabled: Boolean(element.disabled) || element.getAttribute("aria-disabled") === "true",
    visible: isVisible(element),
    nearby_text: nearbyText(element, maxTextChars),
  };
}

function extractDomCandidates(options) {
  const selector = [
    "button",
    "a",
    "input",
    "textarea",
    "select",
    "[role='button']",
    "[contenteditable='true']",
    "[contenteditable='']"
  ].join(",");
  const elements = Array.from(document.querySelectorAll(selector));
  const candidates = [];
  const seenSelectors = new Set();

  for (const element of elements) {
    if (candidates.length >= options.maxElements) {
      break;
    }
    const candidate = candidateFromElement(element, options.maxTextChars);
    if (!candidate.visible || seenSelectors.has(candidate.selector)) {
      continue;
    }
    seenSelectors.add(candidate.selector);
    candidates.push(candidate);
  }
  return candidates;
}
"""
)


class DOMExtractor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def extract(self, page: Page) -> list[DomCandidate]:
        raw_candidates = await page.evaluate(
            f"(options) => {{\n{DOM_EXTRACTOR_JS}\nreturn extractDomCandidates(options);\n}}",
            {
                "maxElements": self.settings.dom_max_elements,
                "maxTextChars": self.settings.dom_max_text_chars,
            },
        )
        if not isinstance(raw_candidates, list):
            return []

        candidates = [
            DomCandidate.model_validate(candidate)
            for candidate in raw_candidates
            if isinstance(candidate, dict) and candidate.get("selector")
        ]
        return self._limit_total_chars(candidates)

    def _limit_total_chars(self, candidates: list[DomCandidate]) -> list[DomCandidate]:
        kept: list[DomCandidate] = []
        total_chars = 0
        for candidate in candidates:
            candidate_chars = len(
                json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False)
            )
            if kept and total_chars + candidate_chars > self.settings.dom_max_total_chars:
                break
            kept.append(candidate)
            total_chars += candidate_chars
        return kept


def candidates_to_jsonable(candidates: list[DomCandidate]) -> list[dict[str, Any]]:
    return [candidate.model_dump(mode="json", exclude_none=True) for candidate in candidates]
