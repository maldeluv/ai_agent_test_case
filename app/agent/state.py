from __future__ import annotations

from pydantic import BaseModel, Field

from app.config import Settings
from app.tools.schemas import ToolResult
from app.utils.truncate import truncate_json_string, truncate_text, truncate_value


class AgentAction(BaseModel):
    step: int
    tool_name: str
    ok: bool
    input_preview: str
    result_preview: str
    error_code: str | None = None


class AgentState(BaseModel):
    user_task: str
    execution_summary: str = ""
    recent_actions: list[AgentAction] = Field(default_factory=list)

    def record_tool_result(
        self,
        *,
        step: int,
        tool_name: str,
        tool_input: dict[str, object],
        result: ToolResult,
        settings: Settings,
    ) -> None:
        input_preview = truncate_json_string(
            truncate_value(
                tool_input,
                max_string_chars=settings.agent_action_max_chars // 2,
                max_list_items=8,
            ),
            max_chars=settings.agent_action_max_chars,
        )
        result_payload = {
            "ok": result.ok,
            "message": result.message,
            "error_code": result.error_code,
            "data": truncate_value(
                result.data,
                max_string_chars=settings.agent_action_max_chars // 2,
                max_list_items=8,
            ),
        }
        result_preview = truncate_json_string(
            result_payload,
            max_chars=settings.agent_action_max_chars,
        )

        self.recent_actions.append(
            AgentAction(
                step=step,
                tool_name=tool_name,
                ok=result.ok,
                input_preview=input_preview,
                result_preview=result_preview,
                error_code=result.error_code,
            )
        )
        self.recent_actions = self.recent_actions[-settings.agent_recent_actions_limit :]
        self._append_summary_line(
            self._summary_line(step=step, tool_name=tool_name, result=result),
            settings=settings,
        )

    def to_context_text(self, settings: Settings) -> str:
        recent_actions = "\n".join(
            (
                f"- step {action.step}: {action.tool_name} "
                f"{'ok' if action.ok else 'failed'}; "
                f"input={action.input_preview}; result={action.result_preview}"
            )
            for action in self.recent_actions
        )
        if not recent_actions:
            recent_actions = "- none"

        summary = self.execution_summary or "No actions executed yet."
        text = f"""Original user task:
{self.user_task}

Compact execution summary:
{summary}

Recent actions:
{recent_actions}

Context policy:
- Do not assume hidden browser state beyond this compact state and current tool results.
- Use query_dom before click_element or type_text when you need selectors.
- Do not ask for full HTML; only compact observations are available.
"""
        max_chars = (
            settings.agent_execution_summary_max_chars
            + settings.agent_recent_actions_limit * settings.agent_action_max_chars
            + 1200
        )
        return truncate_text(text, max_chars=max_chars)

    def _append_summary_line(self, line: str, settings: Settings) -> None:
        summary = f"{self.execution_summary}\n{line}".strip()
        self.execution_summary = truncate_text(
            summary,
            max_chars=settings.agent_execution_summary_max_chars,
        )

    def _summary_line(self, *, step: int, tool_name: str, result: ToolResult) -> str:
        status = "ok" if result.ok else f"failed:{result.error_code or 'unknown'}"
        return f"step {step}: {tool_name} -> {status}; {result.message}"
