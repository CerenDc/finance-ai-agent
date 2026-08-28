from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=10_000)
    thread_id: str | None = Field(default=None, min_length=1, max_length=200)


class AgentResumeRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    thread_id: str = Field(min_length=1, max_length=200)
    decision: Literal["approve", "reject"]


class AgentResponse(BaseModel):
    status: Literal["completed", "approval_required"]
    thread_id: str
    answer: str | None = None
    interrupt: dict[str, Any] | None = None
