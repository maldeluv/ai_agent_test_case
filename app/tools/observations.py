from __future__ import annotations

from pydantic import BaseModel

from app.tools.registry import ToolContext
from app.tools.schemas import EmptyInput, ToolResult
from app.utils.truncate import truncate_text


ACTIVE_LAYER_TEXT_JS = r"""
() => {
  function isVisible(element) {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) {
      return false;
    }
    const style = window.getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) {
      return false;
    }
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0 &&
      rect.left < (window.innerWidth || 0) && rect.top < (window.innerHeight || 0);
  }
  function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === "function") {
      return window.CSS.escape(value);
    }
    return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  }
  function selectorFor(element) {
    if (!element) {
      return null;
    }
    const id = element.getAttribute("id");
    if (id) {
      return `#${cssEscape(id)}`;
    }
    const role = element.getAttribute("role");
    if (role) {
      return `${element.tagName.toLowerCase()}[role="${String(role).replace(/"/g, '\\"')}"]`;
    }
    return element.tagName.toLowerCase();
  }
  function getRole(element) {
    return (element.getAttribute("role") || "").toLowerCase();
  }
  function numericZIndex(element) {
    const value = Number.parseInt(window.getComputedStyle(element).zIndex, 10);
    return Number.isFinite(value) ? value : 0;
  }
  function overlapRatio(element) {
    const rect = element.getBoundingClientRect();
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 1;
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 1;
    const left = Math.max(rect.left, 0);
    const top = Math.max(rect.top, 0);
    const right = Math.min(rect.right, viewportWidth);
    const bottom = Math.min(rect.bottom, viewportHeight);
    return (Math.max(0, right - left) * Math.max(0, bottom - top)) /
      Math.max(1, viewportWidth * viewportHeight);
  }
  function interactiveCount(element) {
    return element.querySelectorAll(
      "button,a,input:not([type='hidden']),textarea,select,[role='button'],[role='link'],[role='textbox'],[contenteditable],[tabindex]:not([tabindex='-1'])"
    ).length;
  }
  function explicitModal(element) {
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
  function score(element) {
    if (!isVisible(element)) {
      return -Infinity;
    }
    const rect = element.getBoundingClientRect();
    if (rect.width < 120 || rect.height < 80) {
      return -Infinity;
    }
    const style = window.getComputedStyle(element);
    const explicit = explicitModal(element);
    const overlap = overlapRatio(element);
    const count = interactiveCount(element);
    if (!explicit && !["fixed", "sticky"].includes(style.position) && numericZIndex(element) <= 0) {
      return -Infinity;
    }
    if (!explicit && (count === 0 || overlap < 0.15)) {
      return -Infinity;
    }
    let value = explicit ? 2000 : 0;
    value += style.position === "fixed" ? 700 : 0;
    value += Math.min(Math.max(numericZIndex(element), 0), 10000) / 10;
    value += Math.min(count, 20) * 80;
    value += Math.min(overlap, 1) * 300;
    return value;
  }
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
      if (["fixed", "sticky"].includes(style.position) && numericZIndex(element) > 0) {
        candidates.push(element);
      }
    }
  }
  let best = null;
  let bestScore = 0;
  for (const candidate of candidates) {
    const candidateScore = score(candidate);
    if (candidateScore > bestScore) {
      best = candidate;
      bestScore = candidateScore;
    }
  }
  if (best && bestScore >= 900) {
    return {
      active_layer_selector: selectorFor(best),
      active_layer_text: best.innerText || best.textContent || "",
    };
  }
  return {
    active_layer_selector: null,
    active_layer_text: null,
  };
}
"""


async def get_current_page_info(input_data: BaseModel, context: ToolContext) -> ToolResult:
    EmptyInput.model_validate(input_data)
    try:
        page = await context.browser.get_active_page()
        title = await page.title()
        visible_text = ""
        active_layer_selector = None

        try:
            evaluate = getattr(page, "evaluate", None)
            active_layer_info = (
                await evaluate(ACTIVE_LAYER_TEXT_JS) if evaluate is not None else {}
            )
            if isinstance(active_layer_info, dict):
                active_layer_text = active_layer_info.get("active_layer_text")
                if active_layer_text:
                    visible_text = str(active_layer_text)
                    active_layer_selector = active_layer_info.get("active_layer_selector")
            if not visible_text:
                visible_text = await page.locator("body").inner_text(timeout=1500)
        except Exception:
            visible_text = ""

        tabs = []
        tabs_error = None
        list_pages = getattr(context.browser, "list_pages", None)
        if list_pages is not None:
            try:
                tabs = await list_pages()
            except Exception as exc:
                tabs = []
                tabs_error = f"{type(exc).__name__}: {exc}"
        active_tab_index = next(
            (tab["index"] for tab in tabs if tab.get("active") is True),
            None,
        )

        return ToolResult.success(
            tool_name="get_current_page_info",
            message="Current page info collected",
            data={
                "url": page.url,
                "title": title,
                "active_tab_index": active_tab_index,
                "active_layer_selector": active_layer_selector,
                "tabs": tabs,
                "tabs_error": tabs_error,
                "short_visible_text": truncate_text(
                    visible_text,
                    max_chars=context.browser.settings.short_visible_text_chars,
                ),
                "hint": (
                    "If this visible text does not match the expected page, call list_tabs "
                    "and switch_tab before deciding the content is missing."
                ),
            },
        )
    except Exception as exc:
        return ToolResult.failure(
            tool_name="get_current_page_info",
            message=f"Failed to collect current page info: {exc}",
            error_code="page_info_failed",
            data={"exception_type": type(exc).__name__},
            next_hint="Ensure the browser session is started.",
        )
