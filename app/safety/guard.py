from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from rich.console import Console

from app.safety.risk_classifier import RiskAssessment, RiskClassifier
from app.tools.schemas import ToolResult
from app.utils.logger import get_console


ConfirmationCallback = Callable[[str, str], bool]


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
        self._pending_approvals: dict[str, str] = {}
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
    ) -> ToolResult | None:
        if tool_name in {"ask_user_confirmation", "finish_task"}:
            return None

        assessment = self.assess_tool_call(tool_name=tool_name, arguments=arguments)
        structured_signature = self._structured_signature(
            tool_name=tool_name,
            arguments=arguments or {},
            category=assessment.category,
        )
        if not assessment.risky or self.is_approved(
            assessment,
            structured_signature=structured_signature,
        ):
            return None

        approval_id = self._approval_id(structured_signature)
        self._pending_approvals[approval_id] = structured_signature
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
            },
            next_hint=(
                "Call ask_user_confirmation with this action_description and approval_id if available. "
                "If the user declines or confirmation is impossible, call finish_task "
                "with status='blocked' or status='need_user_input'. "
                "After approval, retry the same tool call. Do not ask for repeated "
                "confirmation when the approval_id has already been approved."
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
            self.approve_action_description(action_description)
            if approval_id:
                self.approve_pending_action(approval_id)
            else:
                self.approve_latest_pending_action()
        return approved

    def approve_action_description(self, action_description: str) -> None:
        self._approved_signatures.add(self._signature(action_description))
        normalized = self._normalize(action_description)
        if normalized:
            self._approved_texts.add(normalized)

    def approve_latest_pending_action(self) -> None:
        if self._latest_pending_approval_id is None:
            return
        self.approve_pending_action(self._latest_pending_approval_id)

    def approve_pending_action(self, approval_id: str) -> None:
        signature = self._pending_approvals.get(approval_id)
        if signature:
            self._approved_structured_signatures.add(signature)

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
    ) -> str:
        relevant: dict[str, Any] = {
            "category": category,
            "tool_name": tool_name,
        }
        for key in (
            "selector",
            "text",
            "press_enter",
            "url",
        ):
            if key in arguments:
                relevant[key] = arguments[key]
        return self._normalize(str(sorted(relevant.items())))

    def _normalize(self, text: str) -> str:
        return " ".join(text.casefold().split())
