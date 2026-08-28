from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from app.agent.finance_graph import (
    LOCAL_TOOL_NAMES,
    MCP_READ_TOOL_NAMES,
    SYSTEM_PROMPT,
    ask_agent,
    result_answer,
    result_interrupt,
    resume_agent,
    thread_config,
)


def test_hybrid_registry_has_no_duplicates() -> None:
    assert MCP_READ_TOOL_NAMES.isdisjoint(LOCAL_TOOL_NAMES)
    assert LOCAL_TOOL_NAMES == {
        "create_payment_reminder",
        "send_payment_reminder",
    }


def test_prompt_routes_reads_and_sensitive_actions() -> None:
    assert "get_invoice" in SYSTEM_PROMPT
    assert "appelle obligatoirement send_payment_reminder" in SYSTEM_PROMPT
    assert "JAMAIS demander toi-même une confirmation" in SYSTEM_PROMPT
    assert "interrupt()" in SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_ask_agent_forwards_messages_and_thread_config() -> None:
    graph = SimpleNamespace(
        ainvoke=AsyncMock(return_value={"messages": [AIMessage(content="5800 €")]})
    )
    config = thread_config("thread-42")
    result = await ask_agent(graph, "Combien TechNova nous doit-il ?", config)
    assert result_answer(result) == "5800 €"
    invocation, = graph.ainvoke.await_args.args
    assert invocation["messages"][0].content == "Combien TechNova nous doit-il ?"
    assert graph.ainvoke.await_args.kwargs["config"] == config


@pytest.mark.asyncio
async def test_resume_agent_uses_command_and_same_thread() -> None:
    graph = SimpleNamespace(
        ainvoke=AsyncMock(return_value={"messages": [AIMessage(content="cancelled")]})
    )
    config = thread_config("thread-sensitive")
    await resume_agent(graph, "reject", config)
    command, = graph.ainvoke.await_args.args
    assert command.resume == "reject"
    assert graph.ainvoke.await_args.kwargs["config"] is config


def test_result_interrupt_is_json_safe() -> None:
    result = {
        "__interrupt__": [
            SimpleNamespace(value={"invoice_id": "INV-001", "message": "Approve?"})
        ]
    }
    assert result_interrupt(result) == {
        "invoice_id": "INV-001",
        "message": "Approve?",
    }


def test_result_helpers_tolerate_empty_result() -> None:
    assert result_interrupt({}) is None
    assert result_answer({}) == ""
