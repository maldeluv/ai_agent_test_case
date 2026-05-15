from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from app.tools.registry import ToolContext
from app.tools.schemas import ClickElementInput


CLICK_DIAGNOSTICS_JS = r"""
(data) => {
  function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === "function") {
      return window.CSS.escape(value);
    }
    return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  }
  function compactText(value, maxChars = 180) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    return text.length <= maxChars ? text : `${text.slice(0, maxChars).trim()}...`;
  }
  function selectorFor(element) {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) {
      return null;
    }
    const id = element.getAttribute("id");
    if (id) {
      return `#${cssEscape(id)}`;
    }
    const attrs = ["data-testid", "data-test", "data-qa", "aria-label", "name", "role", "type"];
    for (const attr of attrs) {
      const value = element.getAttribute(attr);
      if (value) {
        const attrValue = String(value).replace(/\\/g, "\\\\").replace(/"/g, "\\\"");
        return `${element.tagName.toLowerCase()}[${attr}="${attrValue}"]`;
      }
    }
    return element.tagName.toLowerCase();
  }
  function elementInfo(element) {
    if (!element) {
      return null;
    }
    const rect = element.getBoundingClientRect();
    return {
      tag: element.tagName.toLowerCase(),
      selector: selectorFor(element),
      id: element.getAttribute("id"),
      role: element.getAttribute("role"),
      aria_label: element.getAttribute("aria-label"),
      class_name: compactText(element.getAttribute("class"), 160),
      text: compactText(element.innerText || element.textContent || "", 240),
      rect: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
      pointer_events: window.getComputedStyle(element).pointerEvents,
      z_index: window.getComputedStyle(element).zIndex,
    };
  }
  const target = document.querySelector(data.selector);
  const point = data.point;
  const topElement = document.elementFromPoint(point.x, point.y);
  const targetContainsTop = Boolean(target && topElement && target.contains(topElement));
  const topContainsTarget = Boolean(target && topElement && topElement.contains(target));
  return {
    selector: data.selector,
    requested_position: data.position,
    click_point: point,
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
    },
    target: elementInfo(target),
    element_from_point: elementInfo(topElement),
    target_contains_element_from_point: targetContainsTop,
    element_from_point_contains_target: topContainsTarget,
    intercepted: Boolean(target && topElement && !targetContainsTop),
  };
}
"""


CLICKABLE_ANCESTOR_SELECTOR_JS = r"""
(element) => {
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
  function nthOfTypeSelector(node) {
    const tag = node.tagName.toLowerCase();
    let index = 1;
    let sibling = node.previousElementSibling;
    while (sibling) {
      if (sibling.tagName.toLowerCase() === tag) {
        index += 1;
      }
      sibling = sibling.previousElementSibling;
    }
    return `${tag}:nth-of-type(${index})`;
  }
  function selectorFromAttributes(node) {
    const tag = node.tagName.toLowerCase();
    const id = node.getAttribute("id");
    if (id) {
      const selector = `#${cssEscape(id)}`;
      if (isUniqueSelector(selector)) {
        return selector;
      }
    }
    const attrs = ["data-testid", "data-test", "data-qa", "aria-label", "name", "role", "type"];
    for (const attr of attrs) {
      const value = node.getAttribute(attr);
      if (!value) {
        continue;
      }
      const selector = `${tag}[${attr}="${attrEscape(value)}"]`;
      if (isUniqueSelector(selector)) {
        return selector;
      }
    }
    return null;
  }
  function buildLocalSelector(node) {
    const attrSelector = selectorFromAttributes(node);
    if (attrSelector) {
      return attrSelector;
    }
    const path = [];
    let current = node;
    while (current && current.nodeType === Node.ELEMENT_NODE && current !== document) {
      const currentAttrSelector = selectorFromAttributes(current);
      path.unshift(currentAttrSelector || nthOfTypeSelector(current));
      const selector = path.join(" > ");
      if (isUniqueSelector(selector)) {
        return selector;
      }
      current = current.parentElement;
    }
    return path.join(" > ");
  }
  function isClickable(node) {
    if (!node || node.nodeType !== Node.ELEMENT_NODE) {
      return false;
    }
    const tag = node.tagName.toLowerCase();
    const role = (node.getAttribute("role") || "").toLowerCase();
    const tabindex = node.getAttribute("tabindex");
    const style = window.getComputedStyle(node);
    return (
      ["button", "a", "input", "textarea", "select", "summary"].includes(tag) ||
      ["button", "link", "menuitem", "option", "tab", "treeitem", "checkbox", "radio"].includes(role) ||
      node.hasAttribute("onclick") ||
      typeof node.onclick === "function" ||
      (tabindex !== null && tabindex !== "-1") ||
      style.cursor === "pointer"
    );
  }
  let current = element.parentElement || element;
  let depth = 0;
  while (current && current.nodeType === Node.ELEMENT_NODE && depth < 8) {
    if (isClickable(current)) {
      return buildLocalSelector(current);
    }
    current = current.parentElement;
    depth += 1;
  }
  return buildLocalSelector(element);
}
"""


async def stabilize_page(page: Page, context: ToolContext) -> dict[str, Any]:
    settings = context.browser.settings
    settle_ms = int(getattr(settings, "browser_ui_settle_ms", 700))
    load_timeout_ms = int(getattr(settings, "browser_load_state_timeout_ms", 1500))
    states: list[str] = []

    wait_for_load_state = getattr(page, "wait_for_load_state", None)
    if wait_for_load_state is not None:
        try:
            await wait_for_load_state("domcontentloaded", timeout=load_timeout_ms)
            states.append("domcontentloaded")
        except Exception:
            states.append("domcontentloaded_timeout")

        try:
            await wait_for_load_state("networkidle", timeout=load_timeout_ms)
            states.append("networkidle")
        except Exception:
            states.append("networkidle_timeout")

    wait_for_timeout = getattr(page, "wait_for_timeout", None)
    if settle_ms > 0 and wait_for_timeout is not None:
        await wait_for_timeout(settle_ms)
        states.append(f"settled_{settle_ms}ms")

    return {"states": states}


async def wait_locator_visible(locator: Any, timeout_ms: int) -> None:
    wait_for = getattr(locator, "wait_for", None)
    if wait_for is not None:
        await wait_for(state="visible", timeout=timeout_ms)


async def scroll_locator_into_view(locator: Any, timeout_ms: int) -> None:
    scroll_into_view = getattr(locator, "scroll_into_view_if_needed", None)
    if scroll_into_view is not None:
        await scroll_into_view(timeout=timeout_ms)


def click_point_from_box(
    box: dict[str, float],
    position: str,
) -> dict[str, float]:
    x = float(box["x"])
    y = float(box["y"])
    width = float(box["width"])
    height = float(box["height"])
    padding_x = min(max(width * 0.15, 6), max(width / 2, 1))
    padding_y = min(max(height * 0.15, 6), max(height / 2, 1))

    if position == "left":
        return {"x": x + padding_x, "y": y + height / 2}
    if position == "right":
        return {"x": x + width - padding_x, "y": y + height / 2}
    if position == "top":
        return {"x": x + width / 2, "y": y + padding_y}
    if position == "bottom":
        return {"x": x + width / 2, "y": y + height - padding_y}
    return {"x": x + width / 2, "y": y + height / 2}


async def click_diagnostics(
    page: Page,
    *,
    selector: str,
    position: str,
    point: dict[str, float] | None = None,
) -> dict[str, Any]:
    locator = page.locator(selector)
    count: int | None = None
    box: dict[str, float] | None = None
    computed_point = point
    try:
        count = await locator.count()
    except Exception:
        count = None
    try:
        if count == 1:
            box = await locator.bounding_box(timeout=1000)
        elif count and count > 1:
            box = await locator.first.bounding_box(timeout=1000)
    except Exception:
        box = None

    if computed_point is None and box is not None:
        computed_point = click_point_from_box(box, position)
    if computed_point is None:
        computed_point = {"x": 0.0, "y": 0.0}

    try:
        details = await page.evaluate(
            CLICK_DIAGNOSTICS_JS,
            {
                "selector": selector,
                "position": position,
                "point": computed_point,
            },
        )
    except Exception as exc:
        details = {"diagnostics_error": str(exc)}

    if isinstance(details, dict):
        details["locator_count"] = count
        details["bounding_box"] = box
    return details if isinstance(details, dict) else {"raw_diagnostics": details}


async def click_target(
    args: ClickElementInput,
    page: Page,
    context: ToolContext,
) -> dict[str, Any]:
    timeout_ms = int(getattr(context.browser.settings, "browser_action_timeout_ms", 7000))
    locator = page.locator(args.selector)
    await wait_locator_visible(locator, timeout_ms)
    count_method = getattr(locator, "count", None)
    if count_method is None:
        await locator.click(timeout=timeout_ms)
        return {"method": "normal"}

    count = await count_method()
    if count != 1 and args.strategy != "coordinates":
        raise RuntimeError(f"selector resolved to {count} elements; expected exactly 1")

    target = locator if count == 1 else locator.first
    await scroll_locator_into_view(target, timeout_ms)
    box = await target.bounding_box(timeout=timeout_ms)
    if box is None:
        raise RuntimeError("target element has no visible bounding box")

    point = click_point_from_box(box, args.position)
    diagnostics_before = await click_diagnostics(
        page,
        selector=args.selector,
        position=args.position,
        point=point,
    )

    if args.strategy == "nearest_clickable_ancestor":
        ancestor_selector = await target.evaluate(CLICKABLE_ANCESTOR_SELECTOR_JS)
        if not isinstance(ancestor_selector, str) or not ancestor_selector:
            raise RuntimeError("nearest clickable ancestor selector was not resolved")
        ancestor_locator = page.locator(ancestor_selector)
        await scroll_locator_into_view(ancestor_locator, timeout_ms)
        ancestor_box = await ancestor_locator.bounding_box(timeout=timeout_ms)
        if ancestor_box is None:
            raise RuntimeError("nearest clickable ancestor has no visible bounding box")
        ancestor_point = click_point_from_box(ancestor_box, args.position)
        await ancestor_locator.click(
            timeout=timeout_ms,
            position={
                "x": ancestor_point["x"] - float(ancestor_box["x"]),
                "y": ancestor_point["y"] - float(ancestor_box["y"]),
            },
        )
        return {
            "method": "nearest_clickable_ancestor",
            "clicked_selector": ancestor_selector,
            "diagnostics_before": diagnostics_before,
        }

    if args.strategy == "coordinates":
        await page.mouse.click(point["x"], point["y"])
        return {"method": "coordinates", "diagnostics_before": diagnostics_before}

    await target.click(
        timeout=timeout_ms,
        position={
            "x": point["x"] - float(box["x"]),
            "y": point["y"] - float(box["y"]),
        },
    )
    return {"method": "normal", "diagnostics_before": diagnostics_before}
