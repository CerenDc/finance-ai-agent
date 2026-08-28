import asyncio
import os
import sys

from dotenv import load_dotenv
from mcp import Client, StdioServerParameters, stdio_client


load_dotenv()

EXPECTED_TOOLS = {
    "get_customers",
    "get_invoices",
    "get_overdue_invoices",
    "get_customer_balance",
    "get_invoice",
    "get_company_kpis",
}


async def main() -> None:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp.finance_server"],
        env={
            "FINANCE_API_BASE_URL": os.getenv(
                "FINANCE_API_BASE_URL",
                "http://127.0.0.1:8000",
            )
        },
    )

    async with Client(stdio_client(server)) as client:
        tools_page = await client.list_tools()
        tool_names = {tool.name for tool in tools_page.tools}
        if tool_names != EXPECTED_TOOLS:
            raise RuntimeError(f"Unexpected MCP tools: {sorted(tool_names)}")

        print("Tools MCP disponibles :")
        for tool in tools_page.tools:
            print(f"- {tool.name}: {tool.description}")

        checks = [
            ("get_invoice", {"invoice_id": "INV-001"}),
            ("get_company_kpis", {}),
            ("get_customer_balance", {"customer_id": 1}),
        ]

        for tool_name, arguments in checks:
            result = await client.call_tool(tool_name, arguments)
            if result.is_error:
                raise RuntimeError(f"MCP tool failed: {tool_name}: {result.content}")
            if result.structured_content is None:
                raise RuntimeError(f"Missing structured result for {tool_name}")
            print(f"\n{tool_name}:")
            print(result.structured_content)


if __name__ == "__main__":
    asyncio.run(main())
