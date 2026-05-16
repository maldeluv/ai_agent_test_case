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
    def __init__(self, recorder: list[str], url: str = "https://mail.example/inbox") -> None:
        self.recorder = recorder
        self.url = url

    def locator(self, selector: str) -> ClickRecorderLocator:
        return ClickRecorderLocator(self.recorder, selector)


class FakeClickBrowser:
    def __init__(self) -> None:
        self.settings = SimpleNamespace()
        self.clicks: list[str] = []
        self.page = FakeClickPage(self.clicks)
        self.active_index = 0

    async def get_active_page(self) -> FakeClickPage:
        return self.page

    async def list_pages(self) -> list[dict[str, object]]:
        return [
            {
                "index": self.active_index,
                "active": True,
                "url": self.page.url,
                "title": "Inbox",
            }
        ]


class TypeRecorderLocator:
    def __init__(self, browser: "FakeTypeBrowser") -> None:
        self.browser = browser

    async def wait_for(self, **_: object) -> None:
        return None

    async def scroll_into_view_if_needed(self, **_: object) -> None:
        return None

    async def fill(self, text: str, **_: object) -> None:
        self.browser.filled.append(text)

    async def press(self, key: str, **_: object) -> None:
        self.browser.pressed.append(key)


class FakeTypePage:
    def __init__(self, browser: "FakeTypeBrowser") -> None:
        self.browser = browser

    def locator(self, _: str) -> TypeRecorderLocator:
        return TypeRecorderLocator(self.browser)


class FakeTypeBrowser:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            browser_action_timeout_ms=1000,
            browser_ui_settle_ms=0,
            browser_load_state_timeout_ms=100,
        )
        self.filled: list[str] = []
        self.pressed: list[str] = []
        self.page = FakeTypePage(self)

    async def get_active_page(self) -> FakeTypePage:
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


def test_risk_classifier_detects_type_enter_send_message() -> None:
    classifier = RiskClassifier()

    assessment = classifier.classify(
        "type_text",
        {
            "selector": 'div[role="textbox"]',
            "text": "привет",
            "press_enter": True,
            "action_description": "Type message and press Enter to send",
        },
    )

    assert assessment.risky is True
    assert assessment.category == "send_message"


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
async def test_confirmation_description_approves_matching_concrete_action() -> None:
    registry = create_default_tool_registry()
    browser = FakeClickBrowser()
    guard = SafetyGuard(confirmation_callback=lambda *_: True)
    context = ToolContext(
        browser=browser,  # type: ignore[arg-type]
        safety_guard=guard,
    )

    confirmation = await registry.execute(
        "ask_user_confirmation",
        {
            "reason": "Deleting spam emails is destructive",
            "action_description": "Delete email from inbox",
        },
        context,
    )
    result = await registry.execute(
        "click_element",
        {
            "selector": "button[aria-label='Delete']",
            "action_description": "Delete email from inbox",
        },
        context,
    )

    assert confirmation.ok is True
    assert result.ok is True
    assert browser.clicks == ["button[aria-label='Delete']"]


@pytest.mark.asyncio
async def test_structured_approval_survives_rephrased_send_message_description() -> None:
    registry = create_default_tool_registry()
    browser = FakeTypeBrowser()
    guard = SafetyGuard(confirmation_callback=lambda *_: True)
    context = ToolContext(
        browser=browser,  # type: ignore[arg-type]
        safety_guard=guard,
    )

    blocked = await registry.execute(
        "type_text",
        {
            "selector": 'span[aria-label="Message"]',
            "action_description": "Type hello into chat composer and press Enter to send",
            "text": "hello",
            "press_enter": True,
        },
        context,
    )
    confirmation = await registry.execute(
        "ask_user_confirmation",
        {
            "reason": "Sending a message needs approval",
            "action_description": "Send the text hello in the current chat.",
        },
        context,
    )
    retry = await registry.execute(
        "type_text",
        {
            "selector": 'span[aria-label="Message"]',
            "action_description": "Send message hello now",
            "text": "hello",
            "press_enter": True,
        },
        context,
    )

    assert blocked.ok is False
    assert blocked.error_code == "safety_confirmation_required"
    assert blocked.data["approval_id"]
    assert confirmation.ok is True
    assert confirmation.data["approval_id"] == blocked.data["approval_id"]
    assert retry.ok is True
    assert browser.filled == ["hello"]
    assert browser.pressed == ["Enter"]


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


@pytest.mark.asyncio
async def test_structured_approval_is_single_use() -> None:
    registry = create_default_tool_registry()
    browser = FakeClickBrowser()
    guard = SafetyGuard(confirmation_callback=lambda *_: True)
    context = ToolContext(browser=browser, safety_guard=guard)  # type: ignore[arg-type]
    risky_arguments = {
        "selector": "button[aria-label='Delete']",
        "action_description": "Delete email",
    }

    blocked = await registry.execute("click_element", risky_arguments, context)
    confirmation = await registry.execute(
        "ask_user_confirmation",
        {
            "reason": "Deleting email is irreversible",
            "action_description": blocked.data["action_description"],
            "approval_id": blocked.data["approval_id"],
        },
        context,
    )
    first = await registry.execute("click_element", risky_arguments, context)
    second = await registry.execute("click_element", risky_arguments, context)

    assert blocked.error_code == "safety_confirmation_required"
    assert confirmation.ok is True
    assert first.ok is True
    assert second.ok is False
    assert second.error_code == "safety_confirmation_required"
    assert browser.clicks == ["button[aria-label='Delete']"]


@pytest.mark.asyncio
async def test_structured_approval_does_not_survive_url_change() -> None:
    registry = create_default_tool_registry()
    browser = FakeClickBrowser()
    guard = SafetyGuard(confirmation_callback=lambda *_: True)
    context = ToolContext(browser=browser, safety_guard=guard)  # type: ignore[arg-type]
    risky_arguments = {
        "selector": "button[aria-label='Delete']",
        "action_description": "Delete email",
    }

    blocked = await registry.execute("click_element", risky_arguments, context)
    confirmation = await registry.execute(
        "ask_user_confirmation",
        {
            "reason": "Deleting email is irreversible",
            "action_description": blocked.data["action_description"],
            "approval_id": blocked.data["approval_id"],
        },
        context,
    )
    browser.page.url = "https://mail.example/archive"
    retry = await registry.execute("click_element", risky_arguments, context)

    assert confirmation.ok is True
    assert retry.ok is False
    assert retry.error_code == "safety_confirmation_required"
    assert browser.clicks == []


@pytest.mark.asyncio
async def test_confirmation_without_approval_id_fails_when_multiple_pending() -> None:
    registry = create_default_tool_registry()
    browser = FakeClickBrowser()
    prompts: list[str] = []
    guard = SafetyGuard(
        confirmation_callback=lambda reason, action: prompts.append(action) is None
    )
    context = ToolContext(browser=browser, safety_guard=guard)  # type: ignore[arg-type]

    first = await registry.execute(
        "click_element",
        {"selector": "#delete-1", "action_description": "Delete email 1"},
        context,
    )
    second = await registry.execute(
        "click_element",
        {"selector": "#delete-2", "action_description": "Delete email 2"},
        context,
    )
    confirmation = await registry.execute(
        "ask_user_confirmation",
        {
            "reason": "Deleting emails is irreversible",
            "action_description": "Delete one of the pending emails",
        },
        context,
    )

    assert first.error_code == "safety_confirmation_required"
    assert second.error_code == "safety_confirmation_required"
    assert confirmation.ok is False
    assert confirmation.error_code == "ambiguous_approval_id"
    assert prompts == []


@pytest.mark.asyncio
async def test_batch_approval_cannot_delete_different_item_set() -> None:
    registry = create_default_tool_registry()
    browser = FakeClickBrowser()
    guard = SafetyGuard(confirmation_callback=lambda *_: True)
    context = ToolContext(browser=browser, safety_guard=guard)  # type: ignore[arg-type]
    first_batch = {
        "selector": "#delete-selected",
        "action_description": "Delete selected spam emails",
        "target_context": "Delete 1 selected spam email: Promo Shop / Huge sale",
        "batch_items": [
            {
                "selector": "#mail-1",
                "control_selector": "#mail-1 input",
                "sender": "Promo Shop",
                "subject": "Huge sale",
                "snippet": "unsubscribe",
            }
        ],
    }
    second_batch = {
        **first_batch,
        "target_context": "Delete 1 selected spam email: Bank / Statement",
        "batch_items": [
            {
                "selector": "#mail-2",
                "control_selector": "#mail-2 input",
                "sender": "Bank",
                "subject": "Statement",
                "snippet": "account notice",
            }
        ],
    }
    guard.record_classified_items(
        items=[
            {
                "index": 1,
                "selector": "#mail-1",
                "source_text": "Promo Shop Huge sale unsubscribe",
                "fields": {
                    "sender": "Promo Shop",
                    "subject": "Huge sale",
                    "snippet": "unsubscribe",
                },
                "classification": "spam",
                "recommended_action": "delete_or_mark_spam",
                "confidence": 0.9,
            },
            {
                "index": 2,
                "selector": "#mail-2",
                "source_text": "Bank Statement account notice",
                "fields": {
                    "sender": "Bank",
                    "subject": "Statement",
                    "snippet": "account notice",
                },
                "classification": "suspicious",
                "recommended_action": "delete_or_mark_spam",
                "confidence": 0.9,
            },
        ],
        browser_context={"active_url": browser.page.url, "active_tab_index": 0},
    )

    blocked = await registry.execute("click_element", first_batch, context)
    confirmation = await registry.execute(
        "ask_user_confirmation",
        {
            "reason": "Deleting email is irreversible",
            "action_description": blocked.data["action_description"],
            "approval_id": blocked.data["approval_id"],
        },
        context,
    )
    wrong_retry = await registry.execute("click_element", second_batch, context)
    correct_retry = await registry.execute("click_element", first_batch, context)

    assert confirmation.ok is True
    assert wrong_retry.ok is False
    assert wrong_retry.error_code == "safety_confirmation_required"
    assert correct_retry.ok is True
    assert browser.clicks == ["#delete-selected"]


@pytest.mark.asyncio
async def test_batch_delete_requires_classified_visible_evidence() -> None:
    registry = create_default_tool_registry()
    browser = FakeClickBrowser()
    guard = SafetyGuard(confirmation_callback=lambda *_: True)
    context = ToolContext(browser=browser, safety_guard=guard)  # type: ignore[arg-type]

    result = await registry.execute(
        "click_element",
        {
            "selector": "#delete-selected",
            "action_description": "Delete selected spam emails",
            "target_context": "Delete 1 selected spam email: Promo Shop / Huge sale",
            "batch_items": [
                {
                    "selector": "#mail-1",
                    "control_selector": "#mail-1 input",
                    "sender": "Promo Shop",
                    "subject": "Huge sale",
                    "snippet": "unsubscribe",
                }
            ],
        },
        context,
    )

    assert result.ok is False
    assert result.error_code == "batch_evidence_required"
    assert browser.clicks == []
