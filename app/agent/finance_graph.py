import asyncio
import os
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import MessagesState, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import Command

from app.tools.finance_tools import (
    create_payment_reminder,
    send_payment_reminder,
)


load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MCP_SERVER_FILE = PROJECT_ROOT / "app" / "mcp" / "finance_server.py"

MCP_READ_TOOL_NAMES = {
    "get_customers",
    "get_invoices",
    "get_overdue_invoices",
    "get_customer_balance",
    "get_invoice",
    "get_company_kpis",
}

LOCAL_TOOL_NAMES = {
    "create_payment_reminder",
    "send_payment_reminder",
}


SYSTEM_PROMPT = """
Tu es un agent financier.

Tu réponds aux questions concernant les clients et les factures de
l'entreprise en utilisant les tools adaptés. N'invente jamais de données
financières. Tu peux effectuer plusieurs appels de tools successifs.

Règles obligatoires de routage :

- Si l'utilisateur demande seulement de consulter une facture, utilise
  get_invoice.
- Si l'utilisateur demande seulement de préparer ou rédiger un brouillon de
  relance, utilise create_payment_reminder.
- Si l'utilisateur demande explicitement d'envoyer, d'exécuter ou d'effectuer
  une relance client, récupère d'abord les informations nécessaires puis
  appelle obligatoirement send_payment_reminder avec l'identifiant de facture.
- Après avoir consulté une facture dans le cadre d'une demande d'envoi, ne
  termine pas par une réponse en langage naturel : enchaîne obligatoirement avec
  send_payment_reminder si la facture peut être relancée.

Tu ne dois JAMAIS demander toi-même une confirmation, par exemple
"Voulez-vous confirmer ?", "Puis-je envoyer ?" ou toute formulation
équivalente. L'approbation humaine est entièrement gérée à l'intérieur de
send_payment_reminder avec LangGraph interrupt().

N'exécute jamais l'opération externe d'envoi sans approbation humaine, mais
appelle send_payment_reminder dès qu'un envoi est demandé, car ce tool garantit
lui-même cette approbation avec interrupt().
"""


def create_mcp_client() -> MultiServerMCPClient:
    return MultiServerMCPClient(
        {
            "finance": {
                "transport": "stdio",
                "command": "uv",
                "args": [
                    "run",
                    "--with",
                    "mcp[cli]==2.1.1",
                    "mcp",
                    "run",
                    f"{MCP_SERVER_FILE}:mcp",
                ],
                "env": {
                    "FINANCE_API_BASE_URL": os.getenv(
                        "FINANCE_API_BASE_URL",
                        "http://127.0.0.1:8000",
                    ),
                },
            }
        }
    )


async def create_finance_graph():
    """Discover MCP tools, validate the hybrid registry, and compile the graph."""
    mcp_client = create_mcp_client()
    mcp_read_tools = await mcp_client.get_tools()
    loaded_mcp_names = {mcp_tool.name for mcp_tool in mcp_read_tools}

    if loaded_mcp_names != MCP_READ_TOOL_NAMES:
        missing = MCP_READ_TOOL_NAMES - loaded_mcp_names
        unexpected = loaded_mcp_names - MCP_READ_TOOL_NAMES
        raise RuntimeError(
            "Invalid Finance MCP tool registry: "
            f"missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )

    local_tools = [
        create_payment_reminder,
        send_payment_reminder,
    ]
    tools = [*mcp_read_tools, *local_tools]
    tool_names = [available_tool.name for available_tool in tools]

    if len(tool_names) != len(set(tool_names)):
        duplicates = sorted(
            name for name in set(tool_names) if tool_names.count(name) > 1
        )
        raise RuntimeError(f"Duplicate tools in agent registry: {duplicates}")

    llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0)
    llm_with_tools = llm.bind_tools(tools)

    async def call_agent(state: MessagesState):
        response = await llm_with_tools.ainvoke(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                *state["messages"],
            ]
        )
        return {"messages": [response]}

    builder = StateGraph(MessagesState)
    builder.add_node("agent", call_agent)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")

    checkpointer = InMemorySaver()
    graph = builder.compile(checkpointer=checkpointer)

    print(f"🔌 MCP read tools chargés : {', '.join(sorted(loaded_mcp_names))}")
    print(f"🏠 Tools locaux chargés : {', '.join(sorted(LOCAL_TOOL_NAMES))}")
    print("✅ Aucun doublon dans le registry hybride")

    return graph


async def ask_agent(graph, question: str, config: dict | None = None):
    if config is None:
        config = {
            "configurable": {
                "thread_id": f"finance-{uuid4()}"
            }
        }

    return await graph.ainvoke(
        {"messages": [HumanMessage(content=question)]},
        config=config,
    )


def print_agent_path(result: dict) -> None:
    print("\n--- PARCOURS DE L'AGENT ---")

    for message in result["messages"]:
        for call in getattr(message, "tool_calls", []):
            print(f"\n🔧 Tool : {call['name']}")
            print(f"📥 Arguments : {call['args']}")
            source = (
                "MCP Finance v2 (stdio)"
                if call["name"] in MCP_READ_TOOL_NAMES
                else "LOCAL"
            )
            print(f"📍 Source : {source}")


async def main() -> None:
    graph = await create_finance_graph()
    config = {
        "configurable": {
            "thread_id": "finance-demo-1"
        }
    }

    question = input("\n💬 Pose une question financière : ")
    result = await ask_agent(graph, question, config=config)

    if "__interrupt__" in result:
        interruption = result["__interrupt__"][0]
        approval_request = interruption.value

        print("\n⛔ APPROBATION HUMAINE REQUISE")
        print(f"Message       : {approval_request['message']}")
        print(f"Facture       : {approval_request['invoice_id']}")
        print(f"Destinataire  : {approval_request['destinataire']}")
        print(f"Sujet         : {approval_request['subject']}")
        print(f"Corps         : {approval_request['body']}")

        decision = ""
        while decision not in {"approve", "reject"}:
            decision = input("\nDécision (approve/reject) : ").strip().lower()

        result = await graph.ainvoke(
            Command(resume=decision),
            config=config,
        )

    print_agent_path(result)
    print("\n🤖 RÉPONSE FINALE :")
    print(result["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(main())
