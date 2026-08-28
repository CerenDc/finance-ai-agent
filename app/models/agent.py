from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: str | None = Field(default=None, min_length=1)


class AgentResumeRequest(BaseModel):
    thread_id: str = Field(min_length=1)
    decision: Literal["approve", "reject"]


class AgentResponse(BaseModel):
    status: Literal["completed", "approval_required"]
    thread_id: str
    answer: str | None = None
    interrupt: dict[str, Any] | None = None
