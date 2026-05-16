from __future__ import annotations

import json
from typing import Any

from playwright.async_api import Page

from app.browser.selector_builder import SelectorBuilder
from app.config import Settings
from app.tools.schemas import VisibleItem


CONTENT_EXTRACTOR_JS = (
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
  if (!element || element.nodeType !== Node.ELEMENT_NODE) {
    return false;
  }
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

function visibleText(element, maxChars) {
  return compactText(elementText(element), maxChars);
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
      if (rect.width >= 180 && rect.height >= 80 && current.contains(editable)) {
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

function normalizedClass(element) {
  return String(element.getAttribute("class") || "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 3)
    .join(".");
}

function siblingSignature(element) {
  return [
    element.tagName.toLowerCase(),
    getRole(element),
    normalizedClass(element),
    element.getAttribute("data-testid") || "",
    element.getAttribute("data-test") || "",
    element.getAttribute("data-qa") || "",
  ].join("|");
}

function isControl(element) {
  const tag = element.tagName.toLowerCase();
  const role = getRole(element);
  const type = (element.getAttribute("type") || "").toLowerCase();
  return (
    ["button", "a", "select", "textarea"].includes(tag) ||
    (tag === "input" && type !== "hidden") ||
    ["button", "link", "checkbox", "radio", "switch", "menuitem", "option", "tab"].includes(role) ||
    element.hasAttribute("onclick") ||
    (element.getAttribute("tabindex") !== null && element.getAttribute("tabindex") !== "-1")
  );
}

function controlKind(element) {
  const tag = element.tagName.toLowerCase();
  const role = getRole(element);
  const type = (element.getAttribute("type") || "").toLowerCase();
  if (tag === "input" && type) {
    return type;
  }
  if (role) {
    return role;
  }
  return tag;
}

function controlFromElement(element, maxTextChars) {
  return {
    kind: controlKind(element),
    selector: buildSelector(element),
    text: visibleText(element, Math.min(maxTextChars, 120)),
    aria_label: compactAttr(element, "aria-label", 120),
    title: compactAttr(element, "title", 120),
    role: compactAttr(element, "role", 80),
    type: compactAttr(element, "type", 80),
    checked:
      element.matches("input[type='checkbox'], input[type='radio']") ||
      element.getAttribute("role") === "checkbox" ||
      element.getAttribute("role") === "radio"
        ? Boolean(element.checked) || element.getAttribute("aria-checked") === "true"
        : null,
    disabled: Boolean(element.disabled) || element.getAttribute("aria-disabled") === "true",
  };
}

function collectControls(element, maxTextChars, maxControls) {
  if (maxControls <= 0) {
    return [];
  }
  const controls = [];
  const seen = new Set();
  const selector = [
    "button",
    "a",
    "input:not([type='hidden'])",
    "textarea",
    "select",
    "[role='button']",
    "[role='link']",
    "[role='checkbox']",
    "[role='radio']",
    "[role='switch']",
    "[role='menuitem']",
    "[onclick]",
    "[tabindex]:not([tabindex='-1'])"
  ].join(",");
  for (const control of Array.from(element.querySelectorAll(selector))) {
    if (controls.length >= maxControls) {
      break;
    }
    if (!isVisible(control) || !isControl(control)) {
      continue;
    }
    const item = controlFromElement(control, maxTextChars);
    if (!item.selector || seen.has(item.selector)) {
      continue;
    }
    seen.add(item.selector);
    controls.push(item);
  }
  return controls;
}

function findScrollContainer(element) {
  let current = element.parentElement;
  let depth = 0;
  while (current && current !== document.body && depth < 10) {
    const style = window.getComputedStyle(current);
    const overflowY = style.overflowY;
    const isScrollable =
      ["auto", "scroll"].includes(overflowY) &&
      current.scrollHeight > current.clientHeight;
    if (isScrollable) {
      return buildSelector(current);
    }
    current = current.parentElement;
    depth += 1;
  }
  return null;
}

function matchesTerms(text, terms) {
  if (!terms.length) {
    return 0;
  }
  const lowered = String(text || "").toLowerCase();
  return terms.reduce((score, term) => score + (lowered.includes(term) ? 1 : 0), 0);
}

function isSemanticItem(element) {
  const tag = element.tagName.toLowerCase();
  const role = getRole(element);
  return (
    ["li", "article", "tr"].includes(tag) ||
    ["listitem", "row", "article", "option", "treeitem"].includes(role)
  );
}

function sourceKind(element, explicitKind) {
  if (explicitKind) {
    return explicitKind;
  }
  const tag = element.tagName.toLowerCase();
  const role = getRole(element);
  if (role) {
    return `role:${role}`;
  }
  if (tag) {
    return `tag:${tag}`;
  }
  return "unknown";
}

function itemRank(record, options, terms) {
  const element = record.element;
  const text = elementText(element);
  const rect = element.getBoundingClientRect();
  const viewportWidth = window.innerWidth || 1;
  const viewportHeight = window.innerHeight || 1;
  let rank = record.bonus || 0;

  rank += matchesTerms(text, terms) * 500;
  if (isSemanticItem(element)) {
    rank += 140;
  }
  if (rect.width >= viewportWidth * 0.35) {
    rank += 120;
  }
  if (text.length >= 25) {
    rank += 80;
  }
  if (text.length >= 80) {
    rank += 40;
  }
  if (text.length > options.maxTextChars * 2) {
    rank -= 700;
  }
  if (element.querySelectorAll("li, article, tr, [role='listitem'], [role='row']").length > 3) {
    rank -= 600;
  }
  if (collectControls(element, 80, 3).length > 0) {
    rank += 35;
  }
  if (element.closest("nav, aside, header, footer")) {
    rank -= 180;
  }
  if (rect.height > viewportHeight * 0.75 || rect.width > viewportWidth * 0.98) {
    rank -= 220;
  }
  if (text.length < 8 || rect.height < 8 || rect.width < 80) {
    rank -= 200;
  }
  return rank;
}

function isReasonableItem(element, options) {
  if (!isVisible(element)) {
    return false;
  }
  if (["SCRIPT", "STYLE", "NOSCRIPT", "SVG"].includes(element.tagName)) {
    return false;
  }
  if (element === document.body || element === document.documentElement) {
    return false;
  }
  const rect = element.getBoundingClientRect();
  const text = visibleText(element, options.maxTextChars + 1);
  return text.length >= 8 && rect.width >= 80 && rect.height >= 8 && inViewport(element);
}

function addRecord(recordsByElement, element, kind, bonus, options, terms, order, activeLayer, activeWorkArea) {
  if (!isReasonableItem(element, options)) {
    return order;
  }
  if (activeLayer && !activeLayer.contains(element)) {
    return order;
  }
  if (activeWorkArea && !activeWorkArea.contains(element)) {
    return order;
  }
  const record = {
    element,
    kind,
    bonus,
    order,
  };
  record.rank = itemRank(record, options, terms);
  const existing = recordsByElement.get(element);
  if (!existing || record.rank > existing.rank) {
    recordsByElement.set(element, record);
  }
  return order + 1;
}

function addSemanticItems(recordsByElement, options, terms, order, root, activeLayer, activeWorkArea) {
  const selector = [
    "li",
    "article",
    "tr",
    "[role='listitem']",
    "[role='row']",
    "[role='article']",
    "[role='option']",
    "[role='treeitem']"
  ].join(",");
  for (const element of Array.from(root.querySelectorAll(selector))) {
    order = addRecord(recordsByElement, element, "semantic_item", 230, options, terms, order, activeLayer, activeWorkArea);
  }
  return order;
}

function addRepeatedSiblings(recordsByElement, options, terms, order, root, activeLayer, activeWorkArea) {
  const parents = root ? Array.from(root.querySelectorAll("*")) : [];
  for (const parent of parents) {
    if (!isVisible(parent)) {
      continue;
    }
    const children = Array.from(parent.children).filter((child) => isReasonableItem(child, options));
    if (children.length < 3 || children.length > 250) {
      continue;
    }
    const groups = new Map();
    for (const child of children) {
      const signature = siblingSignature(child);
      const group = groups.get(signature) || [];
      group.push(child);
      groups.set(signature, group);
    }
    for (const group of groups.values()) {
      if (group.length < 3) {
        continue;
      }
      for (const child of group) {
        order = addRecord(recordsByElement, child, "repeated_sibling", 260, options, terms, order, activeLayer, activeWorkArea);
      }
    }
  }
  return order;
}

function addQueryMatchedBlocks(recordsByElement, options, terms, order, root, activeLayer, activeWorkArea) {
  if (!terms.length || !root) {
    return order;
  }
  const elements = Array.from(root.querySelectorAll("*"));
  for (const element of elements) {
    if (!isReasonableItem(element, options)) {
      continue;
    }
    const text = elementText(element);
    if (matchesTerms(text, terms) === 0) {
      continue;
    }
    let target = element;
    let current = element;
    let depth = 0;
    while (current.parentElement && depth < 4) {
      if (isSemanticItem(current) || current.parentElement.children.length >= 3) {
        target = current;
        break;
      }
      current = current.parentElement;
      depth += 1;
    }
    order = addRecord(recordsByElement, target, "query_match", 320, options, terms, order, activeLayer, activeWorkArea);
  }
  return order;
}

function itemFromRecord(record, index, options, activeLayer, activeWorkArea) {
  const element = record.element;
  const rect = rectData(element);
  const selector = buildSelector(element);
  const insideActiveLayer = activeLayer ? activeLayer.contains(element) : true;
  const insideActiveWorkArea = activeWorkArea ? activeWorkArea.contains(element) : true;
  return {
    index,
    selector,
    tag: element.tagName.toLowerCase(),
    role: compactAttr(element, "role", 80),
    text: visibleText(element, options.maxTextChars),
    source_text: visibleText(element, options.maxTextChars),
    aria_label: compactAttr(element, "aria-label", 160),
    title: compactAttr(element, "title", 160),
    source_kind: sourceKind(element, record.kind),
    x: rect.x,
    y: rect.y,
    width: rect.width,
    height: rect.height,
    in_viewport: inViewport(element),
    center_occluded: centerOccluded(element),
    rect,
    selector_stability: selectorStability(selector),
    inside_active_layer: insideActiveLayer,
    active_layer_selector: activeLayer ? buildSelector(activeLayer) : null,
    inside_active_work_area: insideActiveWorkArea,
    active_work_area_selector: activeWorkArea ? buildSelector(activeWorkArea) : null,
    scroll_container_selector: findScrollContainer(element),
    controls: collectControls(
      element,
      options.maxTextChars,
      options.maxControlsPerItem
    ),
  };
}

function extractVisibleItems(options) {
  const terms = queryTerms(options.query || "");
  const activeLayer = findActiveLayer();
  const activeWorkArea = activeLayer ? null : findActiveWorkArea(options.query || "");
  const root = activeLayer || activeWorkArea || document.body || document;
  const recordsByElement = new Map();
  let order = 0;
  order = addSemanticItems(recordsByElement, options, terms, order, root, activeLayer, activeWorkArea);
  order = addRepeatedSiblings(recordsByElement, options, terms, order, root, activeLayer, activeWorkArea);
  order = addQueryMatchedBlocks(recordsByElement, options, terms, order, root, activeLayer, activeWorkArea);

  const records = Array.from(recordsByElement.values()).sort((left, right) => {
    if (right.rank !== left.rank) {
      return right.rank - left.rank;
    }
    const leftRect = left.element.getBoundingClientRect();
    const rightRect = right.element.getBoundingClientRect();
    if (leftRect.y !== rightRect.y) {
      return leftRect.y - rightRect.y;
    }
    if (leftRect.x !== rightRect.x) {
      return leftRect.x - rightRect.x;
    }
    return left.order - right.order;
  });

  const items = [];
  const seenSelectors = new Set();
  for (const record of records) {
    if (items.length >= options.maxItems) {
      break;
    }
    const selector = buildSelector(record.element);
    if (!selector || seenSelectors.has(selector)) {
      continue;
    }
    seenSelectors.add(selector);
    items.push(itemFromRecord(record, items.length + 1, options, activeLayer, activeWorkArea));
  }
  return items;
}
"""
)


class ContentExtractor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def extract(
        self,
        page: Page,
        *,
        query: str,
        max_items: int | None = None,
    ) -> list[VisibleItem]:
        raw_items = await page.evaluate(
            f"(options) => {{\n{CONTENT_EXTRACTOR_JS}\nreturn extractVisibleItems(options);\n}}",
            {
                "query": query,
                "maxItems": min(max_items or self.settings.content_max_items, self.settings.content_max_items),
                "maxTextChars": self.settings.content_max_text_chars,
                "maxControlsPerItem": self.settings.content_max_controls_per_item,
            },
        )
        if not isinstance(raw_items, list):
            return []

        items = [
            VisibleItem.model_validate(item)
            for item in raw_items
            if isinstance(item, dict) and item.get("selector")
        ]
        return self._limit_total_chars(items)

    def _limit_total_chars(self, items: list[VisibleItem]) -> list[VisibleItem]:
        kept: list[VisibleItem] = []
        total_chars = 0
        for item in items:
            item_chars = len(json.dumps(item.model_dump(mode="json"), ensure_ascii=False))
            if kept and total_chars + item_chars > self.settings.content_max_total_chars:
                break
            kept.append(item)
            total_chars += item_chars
        return kept


def visible_items_to_jsonable(items: list[VisibleItem]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json", exclude_none=True) for item in items]
