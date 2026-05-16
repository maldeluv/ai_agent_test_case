from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rich.console import Console

from app.safety.risk_classifier import RiskAssessment, RiskClassifier
from app.tools.schemas import ToolResult
from app.utils.logger import get_console


ConfirmationCallback = Callable[[str, str], bool]


@dataclass(frozen=True)
class PendingApproval:
    approval_id: str
    structured_signature: str
    tool_name: str
    category: str | None
    reason: str
    action_description: str
    target_context: str
    batch_items: list[dict[str, Any]]


class SafetyGuard:
    def __init__(
        self,
        *,
        classifier: RiskClassifier | None = None,
        confirmation_callback: ConfirmationCallback | None = None,
        console: Console | None = None,
    ) -> None:
        self.classifier = classifier or RiskClassifier()
        self.confirmation_callback = confirmation_callback
        self.console = console or get_console()
        self._approved_signatures: set[str] = set()
        self._approved_texts: set[str] = set()
        self._approved_structured_signatures: set[str] = set()
        self._pending_approvals: dict[str, PendingApproval] = {}
        self._classified_evidence: dict[str, dict[str, Any]] = {}
        self._latest_pending_approval_id: str | None = None

    @property
    def latest_pending_approval_id(self) -> str | None:
        return self._latest_pending_approval_id

    def assess_tool_call(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any] | None,
    ) -> RiskAssessment:
        return self.classifier.classify(tool_name, arguments)

    def check_tool_call(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any] | None,
        browser_context: dict[str, Any] | None = None,
    ) -> ToolResult | None:
        if tool_name in {"ask_user_confirmation", "finish_task"}:
            return None

        assessment = self.assess_tool_call(tool_name=tool_name, arguments=arguments)
        batch_workflow_error = self._batch_workflow_error(
            tool_name=tool_name,
            arguments=arguments or {},
            assessment=assessment,
            browser_context=browser_context or {},
        )
        if batch_workflow_error is not None:
            return batch_workflow_error

        structured_signature = self._structured_signature(
            tool_name=tool_name,
            arguments=arguments or {},
            category=assessment.category,
            browser_context=browser_context or {},
        )
        if not assessment.risky or self.is_approved(
            assessment,
            structured_signature=structured_signature,
        ):
            return None

        approval_id = self._approval_id(structured_signature)
        batch_items = self._batch_items(arguments or {})
        self._pending_approvals[approval_id] = PendingApproval(
            approval_id=approval_id,
            structured_signature=structured_signature,
            tool_name=tool_name,
            category=assessment.category,
            reason=assessment.reason,
            action_description=assessment.action_text,
            target_context=self._target_context(arguments or {}),
            batch_items=batch_items,
        )
        self._latest_pending_approval_id = approval_id

        return ToolResult.failure(
            tool_name=tool_name,
            message="Risky action requires explicit user confirmation before execution.",
            error_code="safety_confirmation_required",
            data={
                "approval_id": approval_id,
                "approval_signature": structured_signature,
                "risk_category": assessment.category,
                "reason": assessment.reason,
                "matched_terms": list(assessment.matched_terms),
                "action_description": assessment.action_text,
                "target_context": self._target_context(arguments or {}),
                "batch": self._batch_confirmation_summary(batch_items),
                "page_context": browser_context or {},
            },
            next_hint=(
                "Call ask_user_confirmation with this action_description and approval_id if available. "
                "If the user declines or confirmation is impossible, call finish_task "
                "with status='blocked' or status='need_user_input'. "
                "After approval, retry the same tool call with the same selector, page/tab context, "
                "and batch_items/target_context. Approvals are single-use."
            ),
        )

    def request_confirmation(
        self,
        *,
        reason: str,
        action_description: str,
        approval_id: str | None = None,
    ) -> bool:
        if self.confirmation_callback is not None:
            approved = self.confirmation_callback(reason, action_description)
        else:
            approved = self._prompt_user(
                reason=reason,
                action_description=action_description,
            )

        if approved:
            if approval_id:
                self.approve_pending_action(approval_id)
            else:
                self.approve_action_description(action_description)
        return approved

    def resolve_pending_approval_id(
        self,
        approval_id: str | None,
    ) -> tuple[str | None, ToolResult | None]:
        if approval_id:
            if approval_id not in self._pending_approvals:
                return None, ToolResult.failure(
                    tool_name="ask_user_confirmation",
                    message="Unknown or expired approval_id.",
                    error_code="unknown_approval_id",
                    data={"approval_id": approval_id},
                    next_hint=(
                        "Refresh the risky action by retrying it or call finish_task "
                        "if the action should not continue."
                    ),
                )
            return approval_id, None

        pending_count = len(self._pending_approvals)
        if pending_count == 0:
            return None, None
        if pending_count == 1:
            return next(iter(self._pending_approvals)), None
        return None, ToolResult.failure(
            tool_name="ask_user_confirmation",
            message="Multiple risky actions are pending; approval_id is required.",
            error_code="ambiguous_approval_id",
            data={
                "pending_approval_ids": list(self._pending_approvals),
                "pending_actions": [
                    self._pending_to_jsonable(pending)
                    for pending in self._pending_approvals.values()
                ],
            },
            next_hint=(
                "Call ask_user_confirmation again with the exact approval_id returned "
                "by the specific safety_confirmation_required result."
            ),
        )

    def approve_action_description(self, action_description: str) -> None:
        self._approved_signatures.add(self._signature(action_description))
        normalized = self._normalize(action_description)
        if normalized:
            self._approved_texts.add(normalized)

    def approve_latest_pending_action(self) -> None:
        if self._latest_pending_approval_id is None:
            return
        self.approve_pending_action(self._latest_pending_approval_id)

    def approve_pending_action(self, approval_id: str) -> bool:
        pending = self._pending_approvals.get(approval_id)
        if pending:
            self._approved_structured_signatures.add(pending.structured_signature)
            return True
        return False

    def record_classified_items(
        self,
        *,
        items: list[dict[str, Any]],
        browser_context: dict[str, Any] | None = None,
    ) -> None:
        browser_context = browser_context or {}
        for item in items:
            if not isinstance(item, dict):
                continue
            if not self._item_has_actionable_classification(item):
                continue
            for key in self._item_evidence_keys(item, browser_context):
                self._classified_evidence[key] = item

    def consume_approval_for_tool_call(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any] | None,
        browser_context: dict[str, Any] | None = None,
    ) -> None:
        assessment = self.assess_tool_call(tool_name=tool_name, arguments=arguments)
        if not assessment.risky:
            return

        structured_signature = self._structured_signature(
            tool_name=tool_name,
            arguments=arguments or {},
            category=assessment.category,
            browser_context=browser_context or {},
        )
        self._approved_structured_signatures.discard(structured_signature)
        consumed_ids = [
            approval_id
            for approval_id, pending in self._pending_approvals.items()
            if pending.structured_signature == structured_signature
        ]
        for approval_id in consumed_ids:
            self._pending_approvals.pop(approval_id, None)
        if self._latest_pending_approval_id in consumed_ids:
            self._latest_pending_approval_id = (
                next(reversed(self._pending_approvals), None)
                if self._pending_approvals
                else None
            )
        self._consume_text_approval(assessment.action_text)

    def is_approved(
        self,
        assessment: RiskAssessment,
        *,
        structured_signature: str | None = None,
    ) -> bool:
        if (
            structured_signature is not None
            and structured_signature in self._approved_structured_signatures
        ):
            return True

        action_text = self._normalize(assessment.action_text)
        if self._signature(action_text) in self._approved_signatures:
            return True
        return any(
            approved_text in action_text or action_text in approved_text
            for approved_text in self._approved_texts
        )

    def _prompt_user(self, *, reason: str, action_description: str) -> bool:
        self.console.print("[bold yellow]Confirmation required[/bold yellow]")
        self.console.print(f"[bold]Reason:[/bold] {reason}")
        self.console.print(f"[bold]Action:[/bold] {action_description}")
        try:
            answer = self.console.input(
                "[bold yellow]Allow this action?[/bold yellow] "
                "[dim](y/yes/да, Enter = no):[/dim] "
            )
        except EOFError:
            self.console.print(
                "[yellow]Input stream is unavailable; confirmation was not collected.[/yellow]"
            )
            return False
        return answer.strip().casefold() in {
            "1",
            "true",
            "y",
            "yes",
            "д",
            "да",
            "ok",
            "allow",
            "approve",
        }

    def _signature(self, action_description: str) -> str:
        normalized = self._normalize(action_description)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _approval_id(self, structured_signature: str) -> str:
        return hashlib.sha256(structured_signature.encode("utf-8")).hexdigest()[:16]

    def _structured_signature(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        category: str | None,
        browser_context: dict[str, Any] | None = None,
    ) -> str:
        relevant: dict[str, Any] = {
            "category": category,
            "tool_name": tool_name,
        }
        browser_context = browser_context or {}
        for key in ("active_url", "active_tab_index"):
            if key in browser_context:
                relevant[key] = browser_context[key]
        for key in (
            "selector",
            "text",
            "press_enter",
            "url",
            "target_context",
            "batch_items",
        ):
            if key in arguments:
                relevant[key] = arguments[key]
        return self._normalize(
            json.dumps(relevant, ensure_ascii=False, sort_keys=True, default=str)
        )

    def _batch_workflow_error(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        assessment: RiskAssessment,
        browser_context: dict[str, Any],
    ) -> ToolResult | None:
        if not assessment.risky or assessment.category not in {"delete_email", "mark_spam"}:
            return None
        if not self._looks_like_batch_mail_action(arguments, assessment):
            return None

        batch_items = self._batch_items(arguments)
        if not batch_items:
            return ToolResult.failure(
                tool_name=tool_name,
                message=(
                    "Batch mail delete/spam action requires explicit visible item "
                    "evidence before confirmation."
                ),
                error_code="batch_evidence_required",
                data={
                    "risk_category": assessment.category,
                    "required_workflow": [
                        "collect_visible_items",
                        "classify_items_with_evidence",
                        "prepare_batch_action_confirmation",
                        "ask_user_confirmation",
                        "retry the exact click_element args",
                    ],
                    "action_description": assessment.action_text,
                },
                next_hint=(
                    "Collect and classify the visible mail/list items first, then call "
                    "prepare_batch_action_confirmation and use its click_element_args unchanged."
                ),
            )

        missing_items = [
            item
            for item in batch_items
            if not self._batch_item_has_recorded_evidence(item, browser_context)
        ]
        if not missing_items:
            return None

        return ToolResult.failure(
            tool_name=tool_name,
            message=(
                "Batch mail delete/spam action does not match previously classified "
                "visible evidence."
            ),
            error_code="batch_evidence_required",
            data={
                "risk_category": assessment.category,
                "missing_count": len(missing_items),
                "missing_items": missing_items[:12],
                "recorded_evidence_count": len(self._classified_evidence),
            },
            next_hint=(
                "Use the exact batch_items returned by prepare_batch_action_confirmation "
                "after classify_items_with_evidence. Do not alter item selectors, controls, "
                "or evidence signatures."
            ),
        )

    def _looks_like_batch_mail_action(
        self,
        arguments: dict[str, Any],
        assessment: RiskAssessment,
    ) -> bool:
        if self._batch_items(arguments):
            return True
        text = self._normalize(assessment.action_text)
        return any(
            term in text
            for term in (
                "selected",
                "batch",
                "multiple",
                "spam",
                "emails",
                "messages",
                "выбран",
                "спам",
                "письма",
            )
        )

    def _item_has_actionable_classification(self, item: dict[str, Any]) -> bool:
        classification = self._normalize(str(item.get("classification") or ""))
        recommended_action = self._normalize(str(item.get("recommended_action") or ""))
        confidence = item.get("confidence", 0)
        try:
            confidence_float = float(confidence)
        except (TypeError, ValueError):
            confidence_float = 0.0
        return (
            confidence_float >= 0.35
            and (
                classification in {"spam", "suspicious"}
                or "delete_or_mark_spam" in recommended_action
            )
        )

    def _batch_item_has_recorded_evidence(
        self,
        item: dict[str, Any],
        browser_context: dict[str, Any],
    ) -> bool:
        return any(
            key in self._classified_evidence
            for key in self._item_evidence_keys(item, browser_context)
        )

    def _item_evidence_keys(
        self,
        item: dict[str, Any],
        browser_context: dict[str, Any],
    ) -> set[str]:
        page_key = self._page_context_key(browser_context)
        keys: set[str] = set()

        evidence_signature = str(item.get("evidence_signature") or "").strip()
        if evidence_signature:
            keys.add(f"{page_key}|signature:{self._normalize(evidence_signature)}")

        selector = str(item.get("selector") or "").strip()
        if selector:
            keys.add(f"{page_key}|selector:{selector}")

        control_selector = str(item.get("control_selector") or "").strip()
        if control_selector:
            keys.add(f"{page_key}|control:{control_selector}")

        evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        source_text = str(
            item.get("source_text")
            or evidence.get("source_text")
            or ""
        ).strip()
        if source_text:
            keys.add(f"{page_key}|source:{self._signature(source_text)}")

        fields = item.get("fields") if isinstance(item.get("fields"), dict) else item
        field_values = {
            key: str(fields.get(key) or "").strip()
            for key in ("sender", "subject", "title", "snippet")
            if str(fields.get(key) or "").strip()
        }
        if selector and field_values:
            keys.add(
                f"{page_key}|selector_fields:{selector}|"
                f"{self._signature(json.dumps(field_values, ensure_ascii=False, sort_keys=True))}"
            )
        return keys

    def _page_context_key(self, browser_context: dict[str, Any]) -> str:
        return self._normalize(
            json.dumps(
                {
                    "active_url": browser_context.get("active_url"),
                    "active_tab_index": browser_context.get("active_tab_index"),
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        )

    def _target_context(self, arguments: dict[str, Any]) -> str:
        context = str(arguments.get("target_context") or "").strip()
        if context:
            return context
        batch_items = self._batch_items(arguments)
        if not batch_items:
            return ""
        parts = []
        for index, item in enumerate(batch_items[:8], start=1):
            label = (
                item.get("subject")
                or item.get("title")
                or item.get("sender")
                or item.get("snippet")
                or item.get("source_text")
                or item.get("selector")
                or f"item {index}"
            )
            parts.append(str(label))
        suffix = "" if len(batch_items) <= 8 else f"; +{len(batch_items) - 8} more"
        return f"{len(batch_items)} batch item(s): " + "; ".join(parts) + suffix

    def _batch_items(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        raw_items = arguments.get("batch_items") or []
        if not isinstance(raw_items, list):
            return []
        items: list[dict[str, Any]] = []
        for item in raw_items:
            if isinstance(item, dict):
                items.append({key: value for key, value in item.items() if value is not None})
        return items

    def _batch_confirmation_summary(
        self,
        batch_items: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not batch_items:
            return None
        return {
            "count": len(batch_items),
            "items": batch_items[:12],
            "truncated": len(batch_items) > 12,
        }

    def _pending_to_jsonable(self, pending: PendingApproval) -> dict[str, Any]:
        return {
            "approval_id": pending.approval_id,
            "tool_name": pending.tool_name,
            "category": pending.category,
            "reason": pending.reason,
            "action_description": pending.action_description,
            "target_context": pending.target_context,
            "batch": self._batch_confirmation_summary(pending.batch_items),
        }

    def pending_approval_count(self) -> int:
        return len(self._pending_approvals)

    def describe_pending_approvals(self) -> list[dict[str, Any]]:
        return [
            self._pending_to_jsonable(pending)
            for pending in self._pending_approvals.values()
        ]

    def approve_followup_text(self, text: str) -> str | None:
        if len(self._pending_approvals) != 1:
            return None
        if self._normalize(text) not in {
            "1",
            "true",
            "y",
            "yes",
            "да",
            "д",
            "ok",
            "allow",
            "approve",
            "подтверждаю",
        }:
            return None
        approval_id = next(iter(self._pending_approvals))
        self.approve_pending_action(approval_id)
        return approval_id

    def _consume_text_approval(self, action_description: str) -> None:
        normalized = self._normalize(action_description)
        self._approved_signatures.discard(self._signature(normalized))
        matched_texts = [
            approved_text
            for approved_text in self._approved_texts
            if approved_text in normalized or normalized in approved_text
        ]
        for approved_text in matched_texts:
            self._approved_texts.discard(approved_text)

    def _normalize(self, text: str) -> str:
        return " ".join(text.casefold().split())
