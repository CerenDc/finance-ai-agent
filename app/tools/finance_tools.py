import httpx

from langchain_core.tools import tool
from langgraph.types import interrupt


BASE_URL = "http://127.0.0.1:8000"


@tool
def get_customers():
    """Retrieve all customers."""
    response = httpx.get(
        f"{BASE_URL}/finance/customers",
        timeout=10.0
    )

    response.raise_for_status()

    return response.json()


@tool
def get_invoices():
    """Retrieve all company invoices."""
    response = httpx.get(
        f"{BASE_URL}/finance/invoices",
        timeout=10.0
    )

    response.raise_for_status()

    return response.json()


@tool
def get_overdue_invoices(min_days: int = 1):
    """
    Retrieve unpaid invoices overdue
    by at least min_days.
    """
    response = httpx.get(
        f"{BASE_URL}/finance/invoices/overdue",
        params={
            "min_days": min_days
        },
        timeout=10.0
    )

    response.raise_for_status()

    return response.json()


@tool
def get_customer_balance(customer_id: int):
    """
    Retourne le montant total impayé d'un client
    à partir de son identifiant.
    """
    response = httpx.get(
        f"{BASE_URL}/finance/customers/{customer_id}/balance",
        timeout=10.0
    )

    response.raise_for_status()

    return response.json()


@tool
def get_invoice(invoice_id: str):
    """
    Retourne les informations détaillées
    d'une facture à partir de son identifiant.
    """
    response = httpx.get(
        f"{BASE_URL}/finance/invoices/{invoice_id}",
        timeout=10.0
    )

    response.raise_for_status()

    return response.json()


@tool
def get_company_kpis():
    """
    Retourne les principaux KPI financiers
    de l'entreprise.
    """
    response = httpx.get(
        f"{BASE_URL}/finance/kpis",
        timeout=10.0
    )

    response.raise_for_status()

    return response.json()


@tool
def create_payment_reminder(invoice_id: str):
    """
    Prépare un brouillon de relance pour une facture impayée.
    Ne transmet aucun email au client.
    """
    response = httpx.post(
        f"{BASE_URL}/finance/reminders/draft/{invoice_id}",
        timeout=10.0
    )

    response.raise_for_status()

    return response.json()


@tool
def send_payment_reminder(invoice_id: str):
    """
    Send a payment reminder for an unpaid invoice.

    Use this tool when the user explicitly asks to send, issue, execute,
    or perform a payment reminder. Do NOT ask the user for confirmation
    before calling this tool. Human approval is handled internally by this
    tool using LangGraph interrupt(). The external send operation is never
    executed before that approval.
    """
    draft_response = httpx.post(
        f"{BASE_URL}/finance/reminders/draft/{invoice_id}",
        timeout=10.0,
    )
    draft_response.raise_for_status()
    draft = draft_response.json()

    decision = interrupt(
        {
            "message": "Approuver l'envoi de cette relance de paiement ?",
            "invoice_id": invoice_id,
            "destinataire": draft["to"],
            "subject": draft["subject"],
            "body": draft["body"],
        }
    )

    if not isinstance(decision, str) or decision.strip().lower() != "approve":
        return {
            "invoice_id": invoice_id,
            "to": draft["to"],
            "status": "cancelled",
        }

    send_response = httpx.post(
        f"{BASE_URL}/finance/reminders/send/{invoice_id}",
        timeout=10.0,
    )
    send_response.raise_for_status()

    return send_response.json()
