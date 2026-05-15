from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class StrictBaseModel(BaseModel):
    model_config = {"extra": "forbid"}


class ToolResult(BaseModel):
    ok: bool
    tool_name: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    next_hint: str | None = None

    @classmethod
    def success(
        cls,
        tool_name: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> "ToolResult":
        return cls(
            ok=True,
            tool_name=tool_name,
            message=message,
            data=data or {},
        )

    @classmethod
    def failure(
        cls,
        tool_name: str,
        message: str,
        error_code: str,
        data: dict[str, Any] | None = None,
        next_hint: str | None = None,
    ) -> "ToolResult":
        return cls(
            ok=False,
            tool_name=tool_name,
            message=message,
            data=data or {},
            error_code=error_code,
            next_hint=next_hint,
        )


class EmptyInput(StrictBaseModel):
    pass


class NavigateToUrlInput(StrictBaseModel):
    url: str = Field(min_length=1)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return stripped


class WaitInput(StrictBaseModel):
    seconds: float = Field(gt=0, le=60)


class TakeScreenshotInput(StrictBaseModel):
    full_page: bool = False


class ClickElementInput(StrictBaseModel):
    selector: str = Field(min_length=1)
    action_description: str | None = Field(
        default=None,
        description="Brief description of the intended click, especially before risky actions.",
    )

    @field_validator("selector")
    @classmethod
    def normalize_selector(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("selector must not be blank")
        return stripped


class TypeTextInput(ClickElementInput):
    text: str
    press_enter: bool = False


class AskUserConfirmationInput(StrictBaseModel):
    reason: str = Field(min_length=1)
    action_description: str = Field(min_length=1)


class ScrollPageInput(StrictBaseModel):
    direction: Literal["up", "down"]
    amount: int = Field(default=800, gt=0, le=10000)


class QueryDomInput(StrictBaseModel):
    query: str = Field(min_length=1)


class DomCandidate(StrictBaseModel):
    tag: str
    selector: str
    text: str = ""
    aria_label: str | None = None
    placeholder: str | None = None
    name: str | None = None
    title: str | None = None
    id: str | None = None
    role: str | None = None
    disabled: bool = False
    visible: bool = True
    nearby_text: str = ""


class DomMatch(StrictBaseModel):
    selector: str
    description: str
    confidence: float = Field(ge=0.0, le=1.0)


class DomQueryData(StrictBaseModel):
    found: bool
    answer: str
    matches: list[DomMatch] = Field(default_factory=list)


class FinishTaskInput(StrictBaseModel):
    status: Literal[
        "success",
        "partial_success",
        "failed",
        "blocked",
        "need_user_input",
    ]
    summary: str = Field(min_length=1)
