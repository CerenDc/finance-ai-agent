"""Production FastAPI graph wired to a deterministic LLM for Docker tests."""

from langchain_core.messages import AIMessage, ToolMessage

from app.agent import finance_graph


class SyntheticFinanceLLM:
    """Route the synthetic TechNova question without any external LLM call."""

    def __init__(self, *args, **kwargs) -> None:
        self.tool_names: set[str] = set()

    def bind_tools(self, tools):
        self.tool_names = {available_tool.name for available_tool in tools}
        if "get_customer_balance" not in self.tool_names:
            raise RuntimeError("Synthetic test requires MCP get_customer_balance")
        return self

    async def ainvoke(self, messages):
        last_message = messages[-1]
        if isinstance(last_message, ToolMessage):
            tool_result = str(last_message.content)
            if "TechNova" not in tool_result or "5800" not in tool_result:
                raise RuntimeError("Unexpected synthetic TechNova MCP result")
            return AIMessage(
                content="TechNova nous doit 5 800 € sur 2 factures impayées."
            )

        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "get_customer_balance",
                    "args": {"customer_id": 1},
                    "id": "synthetic-balance-call",
                    "type": "tool_call",
                }
            ],
        )


finance_graph.ChatOpenAI = SyntheticFinanceLLM

from app.main import app  # noqa: E402
