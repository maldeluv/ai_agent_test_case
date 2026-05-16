from __future__ import annotations


SELECTOR_BUILDER_JS = r"""
function cssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === "function") {
    return window.CSS.escape(value);
  }
  return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

function attrEscape(value) {
  return String(value).replace(/\\/g, "\\\\").replace(/"/g, "\\\"");
}

function isUniqueSelector(selector) {
  try {
    return document.querySelectorAll(selector).length === 1;
  } catch {
    return false;
  }
}

function nthOfTypeSelector(element) {
  const tag = element.tagName.toLowerCase();
  let index = 1;
  let sibling = element.previousElementSibling;
  while (sibling) {
    if (sibling.tagName.toLowerCase() === tag) {
      index += 1;
    }
    sibling = sibling.previousElementSibling;
  }
  return `${tag}:nth-of-type(${index})`;
}

function selectorFromAttributes(element) {
  const tag = element.tagName.toLowerCase();
  const id = element.getAttribute("id");
  if (id) {
    const selector = `#${cssEscape(id)}`;
    if (isUniqueSelector(selector)) {
      return selector;
    }
  }

  const attributes = [
    "data-testid",
    "data-test",
    "data-qa",
    "name",
    "aria-label",
    "placeholder",
    "title",
    "role",
    "type",
  ];
  for (const attrName of attributes) {
    const attrValue = element.getAttribute(attrName);
    if (!attrValue) {
      continue;
    }
    const selector = `${tag}[${attrName}="${attrEscape(attrValue)}"]`;
    if (isUniqueSelector(selector)) {
      return selector;
    }
  }

  return null;
}

function buildSelector(element) {
  const attributeSelector = selectorFromAttributes(element);
  if (attributeSelector) {
    return attributeSelector;
  }

  const path = [];
  let current = element;
  while (current && current.nodeType === Node.ELEMENT_NODE && current !== document) {
    const attrSelector = selectorFromAttributes(current);
    if (attrSelector) {
      path.unshift(attrSelector);
      const selector = path.join(" > ");
      if (isUniqueSelector(selector)) {
        return selector;
      }
    } else {
      path.unshift(nthOfTypeSelector(current));
      const selector = path.join(" > ");
      if (isUniqueSelector(selector)) {
        return selector;
      }
    }
    current = current.parentElement;
  }

  return path.join(" > ");
}
"""


class SelectorBuilder:
    @staticmethod
    def script() -> str:
        return SELECTOR_BUILDER_JS
