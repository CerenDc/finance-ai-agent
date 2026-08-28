import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.agent.finance_graph import MCP_READ_TOOL_NAMES
from app.db.database import get_db
from app.db.models import Customer, Invoice
from app.main import app


def test_health(api_client: TestClient) -> None:
    response = api_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_agent_chat_technova_uses_thread_id(api_client, fake_graph) -> None:
    response = api_client.post(
        "/agent/chat",
        json={
            "thread_id": "test-technova",
            "message": "Combien TechNova nous doit-il ?",
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "completed",
        "thread_id": "test-technova",
        "answer": "TechNova nous doit 5 800 € sur 2 factures.",
    }
    _, config = fake_graph.calls[-1]
    assert config == {"configurable": {"thread_id": "test-technova"}}


def test_agent_chat_generates_thread_id(api_client) -> None:
    response = api_client.post("/agent/chat", json={"message": "KPI ?"})
    assert response.status_code == 200
    assert response.json()["thread_id"].startswith("agent-")


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"message": ""},
        {"message": "   "},
        {"message": 42},
        {"message": "ok", "thread_id": "   "},
        {"message": "ok", "thread_id": 123},
    ],
)
def test_agent_chat_rejects_invalid_payloads(api_client, body) -> None:
    response = api_client.post("/agent/chat", json=body)
    assert response.status_code == 422


def test_agent_chat_returns_clean_503(api_client, fake_graph) -> None:
    fake_graph.error = TimeoutError("internal dependency detail")
    response = api_client.post("/agent/chat", json={"message": "KPI ?"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Finance agent dependency unavailable"}
    assert "internal dependency detail" not in response.text


def test_agent_chat_returns_approval_payload(api_client) -> None:
    response = api_client.post(
        "/agent/chat",
        json={
            "thread_id": "sensitive-1",
            "message": "Envoie une relance de paiement pour la facture INV-001",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "approval_required"
    assert payload["thread_id"] == "sensitive-1"
    assert payload["interrupt"]["invoice_id"] == "INV-001"
    assert "answer" not in payload


@pytest.mark.parametrize(
    ("decision", "expected"),
    [("approve", "sent_simulated"), ("reject", "cancelled")],
)
def test_agent_resume_preserves_thread(api_client, fake_graph, decision, expected) -> None:
    response = api_client.post(
        "/agent/resume",
        json={"thread_id": "sensitive-1", "decision": decision},
    )
    assert response.status_code == 200
    assert response.json()["thread_id"] == "sensitive-1"
    assert expected in response.json()["answer"]
    _, config = fake_graph.calls[-1]
    assert config == {"configurable": {"thread_id": "sensitive-1"}}


def test_agent_resume_rejects_unknown_decision(api_client) -> None:
    response = api_client.post(
        "/agent/resume",
        json={"thread_id": "sensitive-1", "decision": "yes"},
    )
    assert response.status_code == 422


def test_agent_resume_returns_clean_503(api_client, fake_graph) -> None:
    fake_graph.error = TimeoutError("checkpoint unavailable")
    response = api_client.post(
        "/agent/resume",
        json={"thread_id": "sensitive-1", "decision": "reject"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "Finance agent dependency unavailable"}
    assert "checkpoint unavailable" not in response.text


def test_finance_endpoints_use_database(api_client) -> None:
    assert api_client.get("/finance/customers").status_code == 200
    assert len(api_client.get("/finance/invoices").json()) == 3
    assert api_client.get("/finance/invoices/INV-001").json()["amount"] == 4500
    assert api_client.get("/finance/customers/1/balance").json() == {
        "customer_id": 1,
        "customer_name": "TechNova",
        "unpaid_invoice_count": 2,
        "unpaid_total": 5800,
    }
    assert len(api_client.get("/finance/invoices/overdue?min_days=50").json()) == 1
    assert api_client.get("/finance/kpis").json()["total_unpaid"] == 5800


def test_finance_not_found_and_paid_reminder(api_client) -> None:
    assert api_client.get("/finance/invoices/UNKNOWN").status_code == 404
    assert api_client.get("/finance/customers/999/balance").status_code == 404
    assert api_client.post("/finance/reminders/draft/UNKNOWN").status_code == 404
    assert api_client.post("/finance/reminders/draft/INV-002").status_code == 400


def test_payment_reminder_draft_is_non_sensitive(api_client) -> None:
    response = api_client.post("/finance/reminders/draft/INV-001")
    assert response.status_code == 200
    assert response.json()["status"] == "draft"
    assert response.json()["to"] == "finance@technova.fr"


def test_database_error_returns_clean_503(api_client) -> None:
    def unavailable_database():
        raise OperationalError("SELECT 1", {}, RuntimeError("private detail"))

    app.dependency_overrides[get_db] = unavailable_database
    response = api_client.get("/finance/customers")
    assert response.status_code == 503
    assert response.json() == {"detail": "Finance database unavailable"}
    assert "private detail" not in response.text


def test_finance_empty_database(api_client, db_session_factory) -> None:
    with db_session_factory.begin() as session:
        session.query(Invoice).delete()
        session.query(Customer).delete()
    assert api_client.get("/finance/customers").json() == []
    assert api_client.get("/finance/invoices").json() == []
    assert api_client.get("/finance/kpis").json() == {
        "invoice_count": 0,
        "total_billed": 0,
        "unpaid_count": 0,
        "total_unpaid": 0,
        "overdue_count": 0,
    }


def test_expected_mcp_read_registry_is_unchanged() -> None:
    assert MCP_READ_TOOL_NAMES == {
        "get_customers",
        "get_invoices",
        "get_overdue_invoices",
        "get_customer_balance",
        "get_invoice",
        "get_company_kpis",
    }
