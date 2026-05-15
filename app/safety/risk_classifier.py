from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RiskAssessment:
    risky: bool
    category: str | None
    reason: str
    action_text: str
    matched_terms: tuple[str, ...] = ()


class RiskClassifier:
    _CATEGORY_TERMS: dict[str, tuple[str, ...]] = {
        "payment": (
            "оплат",
            "payment",
            "pay now",
            "pay",
            "checkout",
            "купить",
            "purchase",
        ),
        "final_order_confirmation": (
            "оформить заказ",
            "подтвердить заказ",
            "place order",
            "confirm order",
            "submit order",
            "final confirmation",
        ),
        "delete_email": (
            "удалить письмо",
            "удалить письма",
            "удалить выбранные письма",
            "удалить email",
            "переместить в корзину",
            "delete email",
            "delete emails",
            "delete message",
            "delete selected",
            "delete spam",
            "move to trash",
            "trash",
            "permanently delete",
        ),
        "mark_spam": (
            "пометить как спам",
            "пометить спам",
            "пометить письма как спам",
            "mark as spam",
            "mark spam",
            "spam",
        ),
        "send_application": (
            "отправить отклик",
            "откликнуться",
            "send application",
            "submit application",
            "apply now",
        ),
        "submit_form": (
            "отправить форму",
            "отправка формы",
            "submit",
            "submit form",
            "send form",
            "submit external",
        ),
        "send_message": (
            "отправить письмо",
            "отправить сообщение",
            "отправка сообщения",
            "send",
            "send email",
            "send message",
            "press enter to send",
        ),
    }

    _RISKY_TOOLS = {"click_element", "type_text"}

    def classify(self, tool_name: str, arguments: dict[str, Any] | None = None) -> RiskAssessment:
        action_text = self._action_text(tool_name, arguments or {})
        if tool_name not in self._RISKY_TOOLS:
            return RiskAssessment(
                risky=False,
                category=None,
                reason="Tool is not considered externally risky.",
                action_text=action_text,
            )

        normalized = self._normalize(action_text)
        for category, terms in self._CATEGORY_TERMS.items():
            matched_terms = tuple(term for term in terms if term in normalized)
            if matched_terms:
                return RiskAssessment(
                    risky=True,
                    category=category,
                    reason=f"Potentially irreversible action detected: {category}.",
                    action_text=action_text,
                    matched_terms=matched_terms,
                )

        return RiskAssessment(
            risky=False,
            category=None,
            reason="No risky terms detected.",
            action_text=action_text,
        )

    def _action_text(self, tool_name: str, arguments: dict[str, Any]) -> str:
        relevant_values = [
            tool_name,
            str(arguments.get("action_description") or ""),
            str(arguments.get("selector") or ""),
            str(arguments.get("text") or ""),
            str(arguments.get("url") or ""),
        ]
        if tool_name == "type_text" and arguments.get("press_enter") is True:
            relevant_values.append("press enter to send")
        return " ".join(value for value in relevant_values if value).strip()

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.casefold()).strip()
