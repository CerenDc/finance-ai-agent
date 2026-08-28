import argparse
import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import MessagesState, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

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


def get_langgraph_postgres_uri() -> str:
    uri = os.getenv("LANGGRAPH_POSTGRES_URI")
    if not uri:
        raise RuntimeError(
            "LANGGRAPH_POSTGRES_URI is not configured. "
            "Add it to .env before starting the Finance agent."
        )
    return uri


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


async def compile_finance_graph(checkpointer: AsyncPostgresSaver):
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

    graph = builder.compile(checkpointer=checkpointer)

    print(f"🔌 MCP read tools chargés : {', '.join(sorted(loaded_mcp_names))}")
    print(f"🏠 Tools locaux chargés : {', '.join(sorted(LOCAL_TOOL_NAMES))}")
    print("✅ Aucun doublon dans le registry hybride")

    return graph


@asynccontextmanager
async def create_finance_graph() -> AsyncIterator:
    """Keep a reconnecting PostgreSQL checkpointer pool open for the graph lifetime."""
    uri = get_langgraph_postgres_uri()
    async with AsyncConnectionPool(
        conninfo=uri,
        min_size=1,
        max_size=10,
        open=False,
        check=AsyncConnectionPool.check_connection,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
    ) as pool:
        checkpointer = AsyncPostgresSaver(pool)
        yield await compile_finance_graph(checkpointer)


async def setup_langgraph_checkpointer() -> None:
    """Create or migrate LangGraph checkpoint tables once during setup."""
    uri = get_langgraph_postgres_uri()
    async with AsyncPostgresSaver.from_conn_string(uri) as checkpointer:
        await checkpointer.setup()
    print("✅ Tables LangGraph PostgreSQL initialisées")


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


async def resume_agent(graph, decision: str, config: dict):
    """Resume a persisted graph interrupt with the supplied thread config."""
    return await graph.ainvoke(
        Command(resume=decision),
        config=config,
    )


def thread_config(thread_id: str) -> dict:
    """Build the persistent LangGraph configuration shared by CLI and API."""
    return {"configurable": {"thread_id": thread_id}}


def result_interrupt(result: dict) -> dict | None:
    """Return the JSON-compatible interrupt payload, when present."""
    interruptions = result.get("__interrupt__", [])
    if not interruptions:
        return None
    value = interruptions[0].value
    return value if isinstance(value, dict) else {"message": str(value)}


def result_answer(result: dict) -> str:
    """Extract a JSON-safe textual answer from a completed graph result."""
    messages = result.get("messages", [])
    if not messages:
        return ""
    content = messages[-1].content
    return content if isinstance(content, str) else str(content)


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finance LangGraph agent")
    parser.add_argument(
        "--thread-id",
        default="finance-demo-1",
        help="Persistent LangGraph conversation thread identifier.",
    )
    parser.add_argument(
        "--resume",
        choices=("approve", "reject"),
        help="Resume a persisted Human Approval interrupt.",
    )
    parser.add_argument(
        "--interrupt-only",
        action="store_true",
        help="Stop the process after persisting an interrupt.",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Create or migrate LangGraph checkpoint tables, then exit.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if args.setup:
        await setup_langgraph_checkpointer()
        return

    config = thread_config(args.thread_id)

    async with create_finance_graph() as graph:
        print(f"🧵 thread_id : {args.thread_id}")

        if args.resume:
            result = await resume_agent(graph, args.resume, config)
        else:
            question = input("\n💬 Pose une question financière : ")
            result = await ask_agent(graph, question, config=config)

        if "__interrupt__" in result:
            approval_request = result_interrupt(result)

            print("\n⛔ APPROBATION HUMAINE REQUISE")
            print(f"Message       : {approval_request['message']}")
            print(f"Facture       : {approval_request['invoice_id']}")
            print(f"Destinataire  : {approval_request['destinataire']}")
            print(f"Sujet         : {approval_request['subject']}")
            print(f"Corps         : {approval_request['body']}")

            if args.interrupt_only:
                print("\n💾 Interrupt persisté. Vous pouvez arrêter ce processus.")
                return

            decision = ""
            while decision not in {"approve", "reject"}:
                decision = input("\nDécision (approve/reject) : ").strip().lower()

            result = await resume_agent(graph, decision, config)

        print_agent_path(result)
        print("\n🤖 RÉPONSE FINALE :")
        print(result["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(main())
