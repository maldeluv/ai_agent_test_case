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
        if not assessment.risky or self.is_approved(assessment):
            return None

        return ToolResult.failure(
            tool_name=tool_name,
            message="Risky action requires explicit user confirmation before execution.",
            error_code="safety_confirmation_required",
            data={
                "risk_category": assessment.category,
                "reason": assessment.reason,
                "matched_terms": list(assessment.matched_terms),
                "action_description": assessment.action_text,
            },
            next_hint=(
                "Call ask_user_confirmation with this action_description. "
                "If the user declines or confirmation is impossible, call finish_task "
                "with status='blocked' or status='need_user_input'. "
                "After approval, retry the exact action."
            ),
        )

    def request_confirmation(self, *, reason: str, action_description: str) -> bool:
        if self.confirmation_callback is not None:
            approved = self.confirmation_callback(reason, action_description)
        else:
            approved = self._prompt_user(reason=reason, action_description=action_description)

        if approved:
            self.approve_action_description(action_description)
        return approved

    def approve_action_description(self, action_description: str) -> None:
        self._approved_signatures.add(self._signature(action_description))

    def is_approved(self, assessment: RiskAssessment) -> bool:
        return self._signature(assessment.action_text) in self._approved_signatures

    def _prompt_user(self, *, reason: str, action_description: str) -> bool:
        self.console.print("[bold yellow]Confirmation required[/bold yellow]")
        self.console.print(f"[bold]Reason:[/bold] {reason}")
        self.console.print(f"[bold]Action:[/bold] {action_description}")
        answer = self.console.input("Allow this action? [y/N]: ").strip().casefold()
        return answer in {"y", "yes", "д", "да"}

    def _signature(self, action_description: str) -> str:
        normalized = " ".join(action_description.casefold().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
