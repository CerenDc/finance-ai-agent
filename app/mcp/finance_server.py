import os
import logging
import sys
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer


load_dotenv()

logger = logging.getLogger("finance_mcp")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

FINANCE_API_BASE_URL = os.getenv(
    "FINANCE_API_BASE_URL",
    "http://127.0.0.1:8000",
).rstrip("/")

mcp = MCPServer(
    "finance",
    instructions=(
        "Read finance customers, invoices, balances, and company KPIs through "
        "the existing Finance FastAPI service. This server exposes no write "
        "or payment-reminder actions."
    ),
)


def _get(path: str, *, params: dict | None = None) -> Any:
    response = httpx.get(
        f"{FINANCE_API_BASE_URL}{path}",
        params=params,
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


@mcp.tool()
def get_customers() -> list[dict[str, Any]]:
    """List every finance customer with its identifier, name, and email."""
    logger.info("[MCP] tool=get_customers")
    return _get("/finance/customers")


@mcp.tool()
def get_invoices() -> list[dict[str, Any]]:
    """List all company invoices, including paid and unpaid invoices."""
    logger.info("[MCP] tool=get_invoices")
    return _get("/finance/invoices")


@mcp.tool()
def get_overdue_invoices(min_days: int = 1) -> list[dict[str, Any]]:
    """List unpaid invoices overdue by at least the requested number of days."""
    logger.info("[MCP] tool=get_overdue_invoices min_days=%s", min_days)
    return _get(
        "/finance/invoices/overdue",
        params={"min_days": min_days},
    )


@mcp.tool()
def get_customer_balance(customer_id: int) -> dict[str, Any]:
    """Get one customer's unpaid invoice count and total unpaid balance."""
    logger.info("[MCP] tool=get_customer_balance customer_id=%s", customer_id)
    return _get(f"/finance/customers/{customer_id}/balance")


@mcp.tool()
def get_invoice(invoice_id: str) -> dict[str, Any]:
    """Get the detailed finance record for a specific invoice identifier."""
    logger.info("[MCP] tool=get_invoice invoice_id=%s", invoice_id)
    return _get(f"/finance/invoices/{invoice_id}")


@mcp.tool()
def get_company_kpis() -> dict[str, Any]:
    """Get aggregate billing, unpaid invoice, and overdue invoice KPIs."""
    logger.info("[MCP] tool=get_company_kpis")
    return _get("/finance/kpis")


if __name__ == "__main__":
    mcp.run()
