from unittest.mock import Mock, call

import httpx
import pytest
from langchain_core.tools import BaseTool

from app.tools import finance_tools


EXPECTED_TOOLS = {
    "get_customers",
    "get_invoices",
    "get_overdue_invoices",
    "get_customer_balance",
    "get_invoice",
    "get_company_kpis",
    "create_payment_reminder",
    "send_payment_reminder",
}


def response_with(payload) -> Mock:
    response = Mock()
    response.json.return_value = payload
    return response


def test_all_finance_tools_are_discovered() -> None:
    discovered = {
        value.name
        for value in vars(finance_tools).values()
        if isinstance(value, BaseTool)
    }
    assert discovered == EXPECTED_TOOLS


@pytest.mark.parametrize(
    ("tool", "arguments", "path", "payload"),
    [
        (finance_tools.get_customers, {}, "/finance/customers", []),
        (finance_tools.get_invoices, {}, "/finance/invoices", []),
        (
            finance_tools.get_customer_balance,
            {"customer_id": 1},
            "/finance/customers/1/balance",
            {"unpaid_total": 5800},
        ),
        (
            finance_tools.get_invoice,
            {"invoice_id": "INV-001"},
            "/finance/invoices/INV-001",
            {"id": "INV-001"},
        ),
        (finance_tools.get_company_kpis, {}, "/finance/kpis", {"invoice_count": 4}),
    ],
)
def test_read_tools_nominal(monkeypatch, tool, arguments, path, payload) -> None:
    get = Mock(return_value=response_with(payload))
    monkeypatch.setattr(finance_tools.httpx, "get", get)
    assert tool.invoke(arguments) == payload
    get.assert_called_once_with(f"{finance_tools.BASE_URL}{path}", timeout=10.0)


def test_overdue_tool_passes_min_days(monkeypatch) -> None:
    get = Mock(return_value=response_with([]))
    monkeypatch.setattr(finance_tools.httpx, "get", get)
    assert finance_tools.get_overdue_invoices.invoke({"min_days": 30}) == []
    get.assert_called_once_with(
        f"{finance_tools.BASE_URL}/finance/invoices/overdue",
        params={"min_days": 30},
        timeout=10.0,
    )


def test_create_reminder_nominal(monkeypatch) -> None:
    payload = {"invoice_id": "INV-001", "status": "draft"}
    post = Mock(return_value=response_with(payload))
    monkeypatch.setattr(finance_tools.httpx, "post", post)
    assert finance_tools.create_payment_reminder.invoke({"invoice_id": "INV-001"}) == payload
    post.assert_called_once_with(
        f"{finance_tools.BASE_URL}/finance/reminders/draft/INV-001",
        timeout=10.0,
    )


@pytest.mark.parametrize("error", [httpx.TimeoutException("timeout"), httpx.ConnectError("down")])
def test_read_tool_propagates_transport_errors(monkeypatch, error) -> None:
    monkeypatch.setattr(finance_tools.httpx, "get", Mock(side_effect=error))
    with pytest.raises(type(error)):
        finance_tools.get_invoice.invoke({"invoice_id": "INV-001"})


def test_read_tool_propagates_http_error(monkeypatch) -> None:
    response = response_with({"detail": "Invoice not found"})
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404",
        request=httpx.Request("GET", "http://finance/INV-404"),
        response=httpx.Response(404),
    )
    monkeypatch.setattr(finance_tools.httpx, "get", Mock(return_value=response))
    with pytest.raises(httpx.HTTPStatusError):
        finance_tools.get_invoice.invoke({"invoice_id": "INV-404"})


def test_sensitive_tool_reject_never_calls_send(monkeypatch) -> None:
    draft = response_with(
        {
            "to": "finance@technova.fr",
            "subject": "Relance",
            "body": "Brouillon",
        }
    )
    post = Mock(return_value=draft)
    monkeypatch.setattr(finance_tools.httpx, "post", post)
    monkeypatch.setattr(finance_tools, "interrupt", Mock(return_value="reject"))
    result = finance_tools.send_payment_reminder.invoke({"invoice_id": "INV-001"})
    assert result["status"] == "cancelled"
    assert post.call_count == 1
    assert "/reminders/send/" not in post.call_args.args[0]


def test_sensitive_tool_approve_calls_send_after_interrupt(monkeypatch) -> None:
    draft = response_with(
        {
            "to": "finance@technova.fr",
            "subject": "Relance",
            "body": "Brouillon",
        }
    )
    sent = response_with(
        {
            "invoice_id": "INV-001",
            "to": "finance@technova.fr",
            "status": "sent_simulated",
        }
    )
    post = Mock(side_effect=[draft, sent])
    approval = Mock(return_value="approve")
    monkeypatch.setattr(finance_tools.httpx, "post", post)
    monkeypatch.setattr(finance_tools, "interrupt", approval)
    result = finance_tools.send_payment_reminder.invoke({"invoice_id": "INV-001"})
    assert result["status"] == "sent_simulated"
    approval.assert_called_once()
    assert post.call_args_list == [
        call(
            f"{finance_tools.BASE_URL}/finance/reminders/draft/INV-001",
            timeout=10.0,
        ),
        call(
            f"{finance_tools.BASE_URL}/finance/reminders/send/INV-001",
            timeout=10.0,
        ),
    ]

