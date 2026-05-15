from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.safety import RiskClassifier, SafetyGuard
from app.tools.registry import ToolContext, create_default_tool_registry


class ClickRecorderLocator:
    def __init__(self, recorder: list[str], selector: str) -> None:
        self.recorder = recorder
        self.selector = selector

    async def click(self, **_: object) -> None:
        self.recorder.append(self.selector)


class FakeClickPage:
    def __init__(self, recorder: list[str]) -> None:
        self.recorder = recorder

    def locator(self, selector: str) -> ClickRecorderLocator:
        return ClickRecorderLocator(self.recorder, selector)


class FakeClickBrowser:
    def __init__(self) -> None:
        self.settings = SimpleNamespace()
        self.clicks: list[str] = []
        self.page = FakeClickPage(self.clicks)

    async def get_active_page(self) -> FakeClickPage:
        return self.page


def test_risk_classifier_detects_dangerous_actions() -> None:
    classifier = RiskClassifier()

    payment = classifier.classify(
        "click_element",
        {
            "selector": "button[aria-label='Оплатить заказ']",
            "action_description": "Подтвердить оплату заказа",
        },
    )
    safe = classifier.classify(
        "click_element",
        {
            "selector": "button[aria-label='Search']",
            "action_description": "Open search",
        },
    )

    assert payment.risky is True
    assert payment.category == "payment"
    assert safe.risky is False


@pytest.mark.asyncio
async def test_safety_guard_blocks_risky_click_before_execution() -> None:
    registry = create_default_tool_registry()
    browser = FakeClickBrowser()
    guard = SafetyGuard(confirmation_callback=lambda *_: False)

    result = await registry.execute(
        "click_element",
        {
            "selector": "button[aria-label='Удалить письмо']",
            "action_description": "Удалить письмо",
        },
        ToolContext(
            browser=browser,  # type: ignore[arg-type]
            safety_guard=guard,
        ),
    )

    assert result.ok is False
    assert result.error_code == "safety_confirmation_required"
    assert result.data["risk_category"] == "delete_email"
    assert browser.clicks == []


@pytest.mark.asyncio
async def test_ask_user_confirmation_approves_exact_risky_action() -> None:
    registry = create_default_tool_registry()
    browser = FakeClickBrowser()
    guard = SafetyGuard(confirmation_callback=lambda *_: True)
    context = ToolContext(
        browser=browser,  # type: ignore[arg-type]
        safety_guard=guard,
    )
    risky_arguments = {
        "selector": "button[aria-label='Удалить письмо']",
        "action_description": "Удалить письмо",
    }
    risky_action = guard.assess_tool_call(
        tool_name="click_element",
        arguments=risky_arguments,
    ).action_text

    confirmation = await registry.execute(
        "ask_user_confirmation",
        {
            "reason": "Deleting email is irreversible",
            "action_description": risky_action,
        },
        context,
    )
    result = await registry.execute(
        "click_element",
        risky_arguments,
        context,
    )

    assert confirmation.ok is True
    assert result.ok is True
    assert browser.clicks == ["button[aria-label='Удалить письмо']"]


@pytest.mark.asyncio
async def test_ask_user_confirmation_decline_blocks_action() -> None:
    registry = create_default_tool_registry()
    guard = SafetyGuard(confirmation_callback=lambda *_: False)

    result = await registry.execute(
        "ask_user_confirmation",
        {
            "reason": "Sending form has external effect",
            "action_description": "click_element button[type='submit'] отправить форму",
        },
        ToolContext(
            browser=FakeClickBrowser(),  # type: ignore[arg-type]
            safety_guard=guard,
        ),
    )

    assert result.ok is False
    assert result.error_code == "user_declined_confirmation"
