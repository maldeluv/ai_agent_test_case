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

function compactAttr(element, name, maxChars) {
  const value = element.getAttribute(name);
  if (!value) {
    return null;
  }
  return compactText(value, maxChars);
}

function queryTerms(query) {
  const normalized = String(query || "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}_]+/gu, " ");
  return Array.from(new Set(normalized.split(/\s+/).filter((term) => term.length >= 3)));
}

function hasMessageComposeIntent(query) {
  const normalized = String(query || "").toLowerCase();
  return [
    "message",
    "send",
    "reply",
    "write",
    "type",
    "composer",
    "compose",
    "textbox",
    "input",
    "сообщ",
    "отправ",
    "напиш",
    "напис",
    "ответ",
    "ввод",
    "поле",
    "текст"
  ].some((term) => normalized.includes(term));
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

function elementText(element) {
  if (!element) {
    return "";
  }
  const tag = element.tagName.toLowerCase();
  if (tag === "input" || tag === "textarea") {
    return element.value || element.getAttribute("value") || "";
  }
  return element.innerText || element.textContent || "";
}

function nearbyText(element, sourceElement, maxChars) {
  const base = sourceElement || element;
  const parent = base.closest("form, section, article, main, li, td, th, div") ||
    element.parentElement;
  if (!parent) {
    return "";
  }
  return compactText(parent.innerText || parent.textContent || "", maxChars);
}

function ariaText(element, maxTextChars) {
  const ids = [
    ...(element.getAttribute("aria-labelledby") || "").split(/\s+/),
    ...(element.getAttribute("aria-describedby") || "").split(/\s+/),
  ].filter(Boolean);
  const chunks = [];
  for (const id of ids) {
    const referenced = document.getElementById(id);
    if (referenced) {
      chunks.push(referenced.innerText || referenced.textContent || "");
    }
  }
  return compactText(chunks.join(" "), maxTextChars);
}

function getRole(element) {
  return (element.getAttribute("role") || "").toLowerCase();
}

function rectData(element) {
  const rect = element.getBoundingClientRect();
  return {
    x: Math.round(rect.x),
    y: Math.round(rect.y),
    width: Math.round(rect.width),
    height: Math.round(rect.height),
  };
}

function inViewport(element) {
  const rect = element.getBoundingClientRect();
  const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;
  const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
  let left = Math.max(rect.left, 0);
  let top = Math.max(rect.top, 0);
  let right = Math.min(rect.right, viewportWidth);
  let bottom = Math.min(rect.bottom, viewportHeight);
  let current = element.parentElement;
  while (current && current !== document.body && current !== document.documentElement) {
    const style = window.getComputedStyle(current);
    const clips = ["auto", "scroll", "hidden", "clip"].includes(style.overflowY) ||
      ["auto", "scroll", "hidden", "clip"].includes(style.overflowX);
    if (clips) {
      const parentRect = current.getBoundingClientRect();
      left = Math.max(left, parentRect.left);
      top = Math.max(top, parentRect.top);
      right = Math.min(right, parentRect.right);
      bottom = Math.min(bottom, parentRect.bottom);
    }
    current = current.parentElement;
  }
  return rect.width > 0 && rect.height > 0 && right > left && bottom > top;
}

function centerOccluded(element) {
  if (!inViewport(element)) {
    return false;
  }
  const rect = element.getBoundingClientRect();
  const x = Math.min(Math.max(rect.left + rect.width / 2, 0), (window.innerWidth || 1) - 1);
  const y = Math.min(Math.max(rect.top + rect.height / 2, 0), (window.innerHeight || 1) - 1);
  const topElement = document.elementFromPoint(x, y);
  return Boolean(topElement && !element.contains(topElement) && !topElement.contains(element));
}

function selectorStability(selector) {
  if (!selector || selector.includes(":nth-of-type(")) {
    return "low";
  }
  if (
    selector.includes("#") ||
    selector.includes("data-testid") ||
    selector.includes("data-test") ||
    selector.includes("data-qa") ||
    selector.includes("[name=")
  ) {
    return "high";
  }
  return "medium";
}

function isNativeInteractive(element) {
  const tag = element.tagName.toLowerCase();
  if (tag === "a") {
    return Boolean(element.getAttribute("href"));
  }
  return ["button", "input", "textarea", "select", "summary"].includes(tag);
}

function isTextInput(element) {
  if (element.tagName.toLowerCase() !== "input") {
    return false;
  }
  const type = (element.getAttribute("type") || "text").toLowerCase();
  return ![
    "button",
    "checkbox",
    "color",
    "file",
    "hidden",
    "image",
    "radio",
    "range",
    "reset",
    "submit",
  ].includes(type);
}

function isEditableElement(element) {
  const tag = element.tagName.toLowerCase();
  const contentEditableAttr = element.getAttribute("contenteditable");
  const contentEditable = (contentEditableAttr || "").toLowerCase();
  return (
    isTextInput(element) ||
    tag === "textarea" ||
    getRole(element) === "textbox" ||
    element.getAttribute("aria-multiline") === "true" ||
    (
      contentEditableAttr !== null &&
      (
        contentEditable === "" ||
        contentEditable === "true" ||
        contentEditable === "plaintext-only"
      )
    )
  );
}

function isActionableRole(element) {
  return [
    "button",
    "link",
    "menuitem",
    "option",
    "tab",
    "treeitem",
    "textbox",
    "combobox",
    "searchbox",
    "switch",
    "checkbox",
    "radio",
  ].includes(getRole(element));
}

function hasUsableLabel(element) {
  return Boolean(
    compactText(elementText(element), 240) ||
    element.getAttribute("aria-label") ||
    element.getAttribute("placeholder") ||
    element.getAttribute("title") ||
    element.getAttribute("name") ||
    element.getAttribute("id") ||
    element.getAttribute("data-testid") ||
    element.getAttribute("data-test") ||
    element.getAttribute("data-qa")
  );
}

function isClickableElement(element) {
  const style = window.getComputedStyle(element);
  const tabindex = element.getAttribute("tabindex");
  return (
    isNativeInteractive(element) ||
    isActionableRole(element) ||
    element.hasAttribute("onclick") ||
    typeof element.onclick === "function" ||
    (tabindex !== null && tabindex !== "-1") ||
    (style.cursor === "pointer" && hasUsableLabel(element))
  );
}

function numericZIndex(element) {
  const value = Number.parseInt(window.getComputedStyle(element).zIndex, 10);
  return Number.isFinite(value) ? value : 0;
}

function viewportOverlapRatio(element) {
  const rect = element.getBoundingClientRect();
  const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 1;
  const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 1;
  const left = Math.max(rect.left, 0);
  const top = Math.max(rect.top, 0);
  const right = Math.min(rect.right, viewportWidth);
  const bottom = Math.min(rect.bottom, viewportHeight);
  const area = Math.max(0, right - left) * Math.max(0, bottom - top);
  return area / Math.max(1, viewportWidth * viewportHeight);
}

function modalInteractiveCount(element) {
  const selector = [
    "button",
    "a",
    "input:not([type='hidden'])",
    "textarea",
    "select",
    "[role='button']",
    "[role='link']",
    "[role='textbox']",
    "[contenteditable]",
    "[tabindex]:not([tabindex='-1'])"
  ].join(",");
  return Array.from(element.querySelectorAll(selector)).filter((node) => isVisible(node)).length;
}

function isExplicitModalElement(element) {
  const tag = element.tagName.toLowerCase();
  const role = getRole(element);
  const ariaModal = (element.getAttribute("aria-modal") || "").toLowerCase();
  const className = String(element.getAttribute("class") || "").toLowerCase();
  return (
    (tag === "dialog" && element.open) ||
    role === "dialog" ||
    role === "alertdialog" ||
    ariaModal === "true" ||
    className.includes("modal") ||
    className.includes("popup") ||
    className.includes("overlay") ||
    className.includes("drawer")
  );
}

function activeLayerScore(element) {
  if (!isVisible(element) || !inViewport(element)) {
    return -Infinity;
  }
  const rect = element.getBoundingClientRect();
  if (rect.width < 120 || rect.height < 80) {
    return -Infinity;
  }
  const style = window.getComputedStyle(element);
  const position = style.position;
  const zIndex = numericZIndex(element);
  const overlapRatio = viewportOverlapRatio(element);
  const explicit = isExplicitModalElement(element);
  const interactiveCount = modalInteractiveCount(element);
  if (!explicit && !["fixed", "sticky"].includes(position) && zIndex <= 0) {
    return -Infinity;
  }
  if (!explicit && interactiveCount === 0) {
    return -Infinity;
  }
  if (!explicit && overlapRatio < 0.15) {
    return -Infinity;
  }

  let score = 0;
  if (explicit) {
    score += 2000;
  }
  if (position === "fixed") {
    score += 700;
  }
  if (position === "sticky") {
    score += 250;
  }
  score += Math.min(Math.max(zIndex, 0), 10000) / 10;
  score += Math.min(interactiveCount, 20) * 80;
  score += Math.min(overlapRatio, 1) * 300;
  if (overlapRatio > 0.75 && !explicit && elementText(element).length < 20) {
    score -= 300;
  }
  return score;
}

function findActiveLayer() {
  const selectors = [
    "dialog[open]",
    "[role='dialog']",
    "[role='alertdialog']",
    "[aria-modal='true']",
    "[class*='modal' i]",
    "[class*='popup' i]",
    "[class*='overlay' i]",
    "[class*='drawer' i]"
  ].join(",");
  const candidates = document.body ? Array.from(document.body.querySelectorAll(selectors)) : [];
  if (document.body) {
    for (const element of Array.from(document.body.querySelectorAll("*"))) {
      const style = window.getComputedStyle(element);
      const zIndex = numericZIndex(element);
      if (
        ["fixed", "sticky"].includes(style.position) &&
        zIndex > 0 &&
        isVisible(element) &&
        inViewport(element)
      ) {
        candidates.push(element);
      }
    }
  }

  let best = null;
  let bestScore = 0;
  for (const candidate of candidates) {
    const score = activeLayerScore(candidate);
    if (score > bestScore) {
      best = candidate;
      bestScore = score;
    }
  }
  return bestScore >= 900 ? best : null;
}

function findActiveWorkArea(query) {
  if (!hasMessageComposeIntent(query)) {
    return null;
  }
  const editableSelector = [
    "textarea",
    "input:not([type='hidden']):not([type='button']):not([type='submit']):not([type='checkbox']):not([type='radio'])",
    "[role='textbox']",
    "[contenteditable]",
    "[aria-multiline='true']"
  ].join(",");
  const editables = document.body ? Array.from(document.body.querySelectorAll(editableSelector)) : [];
  let best = null;
  let bestScore = 0;
  for (const editable of editables) {
    if (!isVisible(editable) || !inViewport(editable)) {
      continue;
    }
    let current = editable;
    let depth = 0;
    while (current && current !== document.body && current !== document.documentElement && depth < 8) {
      const rect = current.getBoundingClientRect();
      const viewportWidth = window.innerWidth || 1;
      const viewportHeight = window.innerHeight || 1;
      const text = elementText(current);
      const role = getRole(current);
      const interactiveCount = modalInteractiveCount(current);
      const listCount = current.querySelectorAll(
        "[role='listitem'], [role='row'], li, article"
      ).length;
      const hasEditable = current.contains(editable);
      if (rect.width >= 180 && rect.height >= 80 && hasEditable) {
        let score = 1000;
        if (["main", "region", "form", "dialog"].includes(role)) {
          score += 180;
        }
        if (current.tagName.toLowerCase() === "main" || current.tagName.toLowerCase() === "form") {
          score += 160;
        }
        if (interactiveCount >= 2) {
          score += 120;
        }
        if (/\b(send|reply|message|compose)\b|отправ|ответ|сообщ/i.test(text)) {
          score += 220;
        }
        if (rect.width < viewportWidth * 0.96) {
          score += 120;
        }
        if (rect.height < viewportHeight * 0.98) {
          score += 80;
        }
        score += Math.min(rect.width * rect.height / 10000, 160);
        score -= Math.min(listCount, 30) * 35;
        if (rect.width >= viewportWidth * 0.98 && rect.height >= viewportHeight * 0.98) {
          score -= 650;
        }
        if (score > bestScore) {
          best = current;
          bestScore = score;
        }
      }
      current = current.parentElement;
      depth += 1;
    }
  }
  return bestScore >= 900 ? best : null;
}

function findActionableAncestor(element) {
  let current = element;
  let depth = 0;
  while (current && current.nodeType === Node.ELEMENT_NODE && depth < 7) {
    if (isVisible(current) && (isClickableElement(current) || isEditableElement(current))) {
      return current;
    }
    current = current.parentElement;
    depth += 1;
  }
  return null;
}

function searchableText(element, sourceElement, maxTextChars) {
  const sourceText = sourceElement && sourceElement !== element ? elementText(sourceElement) : "";
  const values = [
    sourceText,
    elementText(element),
    element.getAttribute("aria-label"),
    element.getAttribute("placeholder"),
    element.getAttribute("name"),
    element.getAttribute("title"),
    element.getAttribute("id"),
    element.getAttribute("role"),
    element.getAttribute("data-testid"),
    element.getAttribute("data-test"),
    element.getAttribute("data-qa"),
    ariaText(element, maxTextChars),
  ];
  return compactText(values.filter(Boolean).join(" "), maxTextChars * 2).toLowerCase();
}

function queryMatchScore(element, sourceElement, terms, maxTextChars) {
  if (!terms.length) {
    return 0;
  }
  const text = searchableText(element, sourceElement, maxTextChars);
  return terms.reduce((score, term) => score + (text.includes(term) ? 1 : 0), 0);
}

function candidateFromElement(element, sourceElement, maxTextChars, terms, activeLayer, activeWorkArea) {
  const tag = element.tagName.toLowerCase();
  const selector = buildSelector(element);
  const sourceText = sourceElement && sourceElement !== element ? elementText(sourceElement) : "";
  const text = sourceText || elementText(element);
  const isEditable = isEditableElement(element);
  const isClickable = isClickableElement(element);
  const rect = rectData(element);
  const candidateInViewport = inViewport(element);
  const insideActiveLayer = activeLayer ? activeLayer.contains(element) : true;
  const insideActiveWorkArea = activeWorkArea ? activeWorkArea.contains(element) : true;

  return {
    tag,
    selector,
    text: compactText(text, maxTextChars),
    aria_label: compactAttr(element, "aria-label", maxTextChars),
    placeholder: compactAttr(element, "placeholder", maxTextChars),
    name: compactAttr(element, "name", maxTextChars),
    title: compactAttr(element, "title", maxTextChars),
    id: compactAttr(element, "id", maxTextChars),
    role: compactAttr(element, "role", maxTextChars),
    class_name: compactAttr(element, "class", 120),
    contenteditable: compactAttr(element, "contenteditable", maxTextChars),
    aria_multiline: compactAttr(element, "aria-multiline", maxTextChars),
    aria_describedby: compactAttr(element, "aria-describedby", maxTextChars),
    data_testid: compactAttr(element, "data-testid", maxTextChars),
    data_test: compactAttr(element, "data-test", maxTextChars),
    data_qa: compactAttr(element, "data-qa", maxTextChars),
    href: compactAttr(element, "href", maxTextChars),
    type: compactAttr(element, "type", maxTextChars),
    tabindex: compactAttr(element, "tabindex", maxTextChars),
    is_clickable: isClickable,
    is_editable: isEditable,
    query_match_score: queryMatchScore(element, sourceElement, terms, maxTextChars),
    disabled: Boolean(element.disabled) || element.getAttribute("aria-disabled") === "true",
    visible: isVisible(element) && candidateInViewport,
    in_viewport: candidateInViewport,
    center_occluded: centerOccluded(element),
    rect,
    selector_stability: selectorStability(selector),
    inside_active_layer: insideActiveLayer,
    active_layer_selector: activeLayer ? buildSelector(activeLayer) : null,
    inside_active_work_area: insideActiveWorkArea,
    active_work_area_selector: activeWorkArea ? buildSelector(activeWorkArea) : null,
    nearby_text: nearbyText(element, sourceElement, maxTextChars),
  };
}

function candidateRank(record, terms, maxTextChars) {
  const element = record.element;
  const sourceElement = record.sourceElement || element;
  let rank = record.bonus || 0;
  const matches = queryMatchScore(element, sourceElement, terms, maxTextChars);
  rank += matches * 500;
  if (isEditableElement(element)) {
    rank += 260;
  }
  if (isClickableElement(element)) {
    rank += 80;
  }
  if (isNativeInteractive(element)) {
    rank += 40;
  }
  if (hasUsableLabel(element)) {
    rank += 20;
  }
  if (record.activeWorkArea && record.activeWorkArea.contains(element)) {
    rank += 900;
  } else if (record.activeWorkArea) {
    rank -= 900;
  }
  if (Boolean(element.disabled) || element.getAttribute("aria-disabled") === "true") {
    rank -= 1000;
  }
  return rank;
}

function extractDomCandidates(options) {
  const terms = queryTerms(options.query || "");
  const activeLayer = findActiveLayer();
  const activeWorkArea = activeLayer ? null : findActiveWorkArea(options.query || "");
  const root = activeLayer || activeWorkArea || document;
  const selector = [
    "button",
    "a",
    "input",
    "textarea",
    "select",
    "summary",
    "[role='button']",
    "[role='link']",
    "[role='menuitem']",
    "[role='option']",
    "[role='tab']",
    "[role='treeitem']",
    "[role='textbox']",
    "[role='combobox']",
    "[role='searchbox']",
    "[role='switch']",
    "[role='checkbox']",
    "[role='radio']",
    "[aria-multiline='true']",
    "[contenteditable]",
    "[placeholder]",
    "[aria-label]",
    "[onclick]",
    "[tabindex]:not([tabindex='-1'])",
    "[data-testid]",
    "[data-test]",
    "[data-qa]"
  ].join(",");
  const recordsByElement = new Map();
  let order = 0;

  function addElement(element, sourceElement, bonus) {
    if (!element || element.nodeType !== Node.ELEMENT_NODE || !isVisible(element)) {
      return;
    }
    if (activeLayer && !activeLayer.contains(element)) {
      return;
    }
    if (activeWorkArea && !activeWorkArea.contains(element)) {
      return;
    }
    if (!isClickableElement(element) && !isEditableElement(element) && !hasUsableLabel(element)) {
      return;
    }
    const record = {
      element,
      sourceElement: sourceElement || element,
      bonus: bonus || 0,
      activeWorkArea,
      order: order++,
    };
    record.rank = candidateRank(record, terms, options.maxTextChars);
    const existing = recordsByElement.get(element);
    if (!existing || record.rank > existing.rank) {
      recordsByElement.set(element, record);
    }
  }

  for (const element of Array.from(root.querySelectorAll(selector))) {
    addElement(element, element, 40);
  }

  const bodyElements = root ? Array.from(root.querySelectorAll("*")) : [];
  for (const element of bodyElements) {
    if (!isVisible(element)) {
      continue;
    }

    if (isClickableElement(element) || isEditableElement(element)) {
      addElement(element, element, 20);
    }

    if (terms.length && queryMatchScore(element, element, terms, options.maxTextChars) > 0) {
      const target = findActionableAncestor(element) || element;
      addElement(target, element, 220);
    }
  }

  const records = Array.from(recordsByElement.values()).sort((left, right) => {
    if (right.rank !== left.rank) {
      return right.rank - left.rank;
    }
    return left.order - right.order;
  });

  const candidates = [];
  const seenSelectors = new Set();

  for (const record of records) {
    if (candidates.length >= options.maxElements) {
      break;
    }
    const candidate = candidateFromElement(
      record.element,
      record.sourceElement,
      options.maxTextChars,
      terms,
      activeLayer,
      activeWorkArea
    );
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

    async def extract(self, page: Page, query: str = "") -> list[DomCandidate]:
        raw_candidates = await page.evaluate(
            f"(options) => {{\n{DOM_EXTRACTOR_JS}\nreturn extractDomCandidates(options);\n}}",
            {
                "maxElements": self.settings.dom_max_elements,
                "maxTextChars": self.settings.dom_max_text_chars,
                "query": query,
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
