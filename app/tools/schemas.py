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


class BatchActionItem(StrictBaseModel):
    selector: str | None = None
    control_selector: str | None = None
    evidence_signature: str | None = None
    item_index: int | None = Field(default=None, ge=1)
    title: str | None = None
    sender: str | None = None
    subject: str | None = None
    snippet: str | None = None
    source_text: str | None = None


class ClickElementInput(StrictBaseModel):
    selector: str = Field(min_length=1)
    action_description: str | None = Field(
        default=None,
        description="Brief description of the intended click, especially before risky actions.",
    )
    target_context: str | None = Field(
        default=None,
        description=(
            "Brief visible context for the exact target or batch being acted on. "
            "For batch risky actions include count and item/control selectors."
        ),
    )
    batch_items: list[BatchActionItem] = Field(
        default_factory=list,
        description=(
            "Exact visible items covered by a batch risky action, such as selected "
            "emails to delete or mark as spam."
        ),
    )
    position: Literal["center", "left", "right", "top", "bottom"] = Field(
        default="center",
        description="Where inside the element to click. Useful when the center is overlapped.",
    )
    strategy: Literal["normal", "nearest_clickable_ancestor", "coordinates"] = Field(
        default="normal",
        description=(
            "Click strategy. normal uses Playwright actionability; "
            "nearest_clickable_ancestor clicks an actionable ancestor; "
            "coordinates clicks a computed point after diagnostics."
        ),
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
    approval_id: str | None = Field(
        default=None,
        description="Structured approval id returned by safety_confirmation_required, when available.",
    )


class ScrollPageInput(StrictBaseModel):
    direction: Literal["up", "down"]
    amount: int = Field(default=800, gt=0, le=10000)


class ScrollElementInput(ScrollPageInput):
    selector: str = Field(min_length=1)

    @field_validator("selector")
    @classmethod
    def normalize_selector(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("selector must not be blank")
        return stripped


class QueryDomInput(StrictBaseModel):
    query: str = Field(min_length=1)


class SwitchTabInput(StrictBaseModel):
    index: int = Field(ge=0)


class ExtractVisibleItemsInput(StrictBaseModel):
    query: str = Field(
        min_length=1,
        description="What visible content/list/table/card items should be extracted and analyzed.",
    )
    max_items: int = Field(default=20, ge=1, le=100)


class CollectVisibleItemsInput(StrictBaseModel):
    query: str = Field(
        min_length=1,
        description="What visible list/table/card/mail items should be collected.",
    )
    target_count: int = Field(default=10, ge=1, le=100)
    max_scroll_steps: int = Field(default=8, ge=0, le=50)
    scroll_amount: int = Field(default=700, ge=50, le=10000)
    container_selector: str | None = Field(
        default=None,
        description="Optional known inner scroll container selector.",
    )


class ClassifyItemsWithEvidenceInput(StrictBaseModel):
    query: str = Field(
        min_length=1,
        description="Classification or analysis to perform on the provided visible evidence.",
    )
    items: list["VisibleItem"] = Field(
        min_length=1,
        description="Visible items previously returned by collect_visible_items or extract_visible_items.",
    )


class PrepareBatchActionConfirmationInput(StrictBaseModel):
    action: Literal["delete", "mark_spam"]
    action_selector: str = Field(
        min_length=1,
        description="Selector for the global action control to click after confirmation.",
    )
    items: list["ContentItemAnalysis"] = Field(
        min_length=1,
        description="Classified visible evidence items to include in the risky batch.",
    )
    classification_filter: list[str] = Field(
        default_factory=lambda: ["spam", "suspicious"],
        description="Only items with these classifications are included.",
    )
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str | None = Field(
        default=None,
        description="Optional user-facing reason for confirmation.",
    )


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
    class_name: str | None = None
    contenteditable: str | None = None
    aria_multiline: str | None = None
    aria_describedby: str | None = None
    data_testid: str | None = None
    data_test: str | None = None
    data_qa: str | None = None
    href: str | None = None
    type: str | None = None
    tabindex: str | None = None
    is_clickable: bool = False
    is_editable: bool = False
    query_match_score: int = 0
    disabled: bool = False
    visible: bool = True
    in_viewport: bool = True
    center_occluded: bool = False
    rect: dict[str, float] = Field(default_factory=dict)
    selector_stability: Literal["high", "medium", "low"] = "medium"
    nearby_text: str = ""


class DomMatch(StrictBaseModel):
    selector: str
    description: str
    confidence: float = Field(ge=0.0, le=1.0)


class DomQueryData(StrictBaseModel):
    found: bool
    answer: str
    matches: list[DomMatch] = Field(default_factory=list)
    error_code: str | None = None
    raw_preview: str | None = None


class VisibleItemControl(StrictBaseModel):
    kind: str
    selector: str
    text: str = ""
    aria_label: str | None = None
    title: str | None = None
    role: str | None = None
    type: str | None = None
    checked: bool | None = None
    disabled: bool = False


class VisibleItem(StrictBaseModel):
    index: int = Field(ge=1)
    selector: str
    tag: str
    role: str | None = None
    text: str = ""
    aria_label: str | None = None
    title: str | None = None
    source_kind: str = "unknown"
    source_text: str | None = None
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    in_viewport: bool = True
    center_occluded: bool = False
    rect: dict[str, float] = Field(default_factory=dict)
    selector_stability: Literal["high", "medium", "low"] = "medium"
    scroll_container_selector: str | None = None
    controls: list[VisibleItemControl] = Field(default_factory=list)


class ContentItemAnalysis(StrictBaseModel):
    index: int = Field(ge=1)
    selector: str | None = None
    item_type: str = "unknown"
    fields: dict[str, str] = Field(default_factory=dict)
    summary: str = ""
    classification: str | None = None
    reason: str | None = None
    recommended_action: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    source_text: str = ""
    evidence: dict[str, str] = Field(default_factory=dict)
    scroll_container_selector: str | None = None
    controls: list[VisibleItemControl] = Field(default_factory=list)


class ContentQueryData(StrictBaseModel):
    found: bool
    answer: str
    items: list[ContentItemAnalysis] = Field(default_factory=list)
    error_code: str | None = None
    raw_preview: str | None = None


class FinishTaskInput(StrictBaseModel):
    status: Literal[
        "success",
        "partial_success",
        "failed",
        "blocked",
        "need_user_input",
    ]
    summary: str = Field(min_length=1)


ClassifyItemsWithEvidenceInput.model_rebuild()
PrepareBatchActionConfirmationInput.model_rebuild()
