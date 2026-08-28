import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from app.agent.finance_graph import (
    ask_agent,
    result_answer,
    result_interrupt,
    resume_agent,
    thread_config,
)
from app.models.agent import AgentChatRequest, AgentResponse, AgentResumeRequest


router = APIRouter(prefix="/agent", tags=["agent"])
logger = logging.getLogger(__name__)


def _service_unavailable(operation: str, thread_id: str, exc: Exception) -> None:
    logger.exception(
        "Finance agent %s failed for thread_id=%s",
        operation,
        thread_id,
        exc_info=True,
    )
    raise HTTPException(
        status_code=503,
        detail="Finance agent dependency unavailable",
    ) from exc


def _response(result: dict, thread_id: str) -> AgentResponse:
    interruption = result_interrupt(result)
    if interruption is not None:
        return AgentResponse(
            status="approval_required",
            thread_id=thread_id,
            interrupt=interruption,
        )
    return AgentResponse(
        status="completed",
        thread_id=thread_id,
        answer=result_answer(result),
    )


@router.post("/chat", response_model=AgentResponse, response_model_exclude_none=True)
async def chat(payload: AgentChatRequest, request: Request) -> AgentResponse:
    thread_id = payload.thread_id or f"agent-{uuid4()}"
    config = thread_config(thread_id)
    try:
        result = await ask_agent(
            request.app.state.finance_graph,
            payload.message,
            config=config,
        )
    except Exception as exc:
        _service_unavailable("chat", thread_id, exc)
    return _response(result, thread_id)


@router.post("/resume", response_model=AgentResponse, response_model_exclude_none=True)
async def resume(payload: AgentResumeRequest, request: Request) -> AgentResponse:
    config = thread_config(payload.thread_id)
    try:
        result = await resume_agent(
            request.app.state.finance_graph,
            payload.decision,
            config,
        )
    except Exception as exc:
        _service_unavailable("resume", payload.thread_id, exc)
    return _response(result, payload.thread_id)
