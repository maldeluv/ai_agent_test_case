from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


AgentStatus = Literal[
    "success",
    "partial_success",
    "failed",
    "blocked",
    "need_user_input",
]


class AgentRunResult(BaseModel):
    status: AgentStatus
    summary: str
    steps_used: int
