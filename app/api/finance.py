from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Customer, Invoice


router = APIRouter(prefix="/finance", tags=["finance"])

DbSession = Annotated[Session, Depends(get_db)]


def _json_amount(amount: float) -> int | float:
    """Preserve the integer-looking amounts returned by V4."""
    return int(amount) if amount.is_integer() else amount


def _customer_json(customer: Customer) -> dict:
    return {"id": customer.id, "name": customer.name, "email": customer.email}


def _invoice_json(invoice: Invoice) -> dict:
    return {
        "id": invoice.id,
        "customer_id": invoice.customer_id,
        "amount": _json_amount(invoice.amount),
        "status": invoice.status,
        "days_overdue": invoice.days_overdue,
    }


def _get_invoice_or_404(db: Session, invoice_id: str) -> Invoice:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


def _get_customer_or_404(db: Session, customer_id: int) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


def _get_reminder_data(db: Session, invoice_id: str) -> tuple[Invoice, Customer]:
    invoice = _get_invoice_or_404(db, invoice_id)
    if invoice.status == "paid":
        raise HTTPException(status_code=400, detail="Invoice already paid")
    customer = _get_customer_or_404(db, invoice.customer_id)
    return invoice, customer


@router.get("/customers")
def get_customers(db: DbSession):
    customers = db.scalars(select(Customer).order_by(Customer.id)).all()
    return [_customer_json(customer) for customer in customers]


@router.get("/customers/{customer_id}")
def get_customer(customer_id: int, db: DbSession):
    return _customer_json(_get_customer_or_404(db, customer_id))


@router.get("/invoices")
def get_invoices(db: DbSession):
    invoices = db.scalars(select(Invoice).order_by(Invoice.id)).all()
    return [_invoice_json(invoice) for invoice in invoices]


@router.get("/invoices/overdue")
def get_overdue_invoices(db: DbSession, min_days: int = 1):
    invoices = db.scalars(
        select(Invoice)
        .where(
            Invoice.status == "unpaid",
            Invoice.days_overdue >= min_days,
        )
        .order_by(Invoice.id)
    ).all()
    return [_invoice_json(invoice) for invoice in invoices]


@router.get("/customers/{customer_id}/balance")
def get_customer_balance(customer_id: int, db: DbSession):
    customer = _get_customer_or_404(db, customer_id)
    unpaid_invoice_count, unpaid_total = db.execute(
        select(
            func.count(Invoice.id),
            func.coalesce(func.sum(Invoice.amount), 0.0),
        ).where(
            Invoice.customer_id == customer_id,
            Invoice.status == "unpaid",
        )
    ).one()

    return {
        "customer_id": customer_id,
        "customer_name": customer.name,
        "unpaid_invoice_count": unpaid_invoice_count,
        "unpaid_total": _json_amount(float(unpaid_total)),
    }


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: str, db: DbSession):
    return _invoice_json(_get_invoice_or_404(db, invoice_id))


@router.get("/kpis")
def get_company_kpis(db: DbSession):
    invoice_count, total_billed = db.execute(
        select(
            func.count(Invoice.id),
            func.coalesce(func.sum(Invoice.amount), 0.0),
        )
    ).one()
    unpaid_count, total_unpaid = db.execute(
        select(
            func.count(Invoice.id),
            func.coalesce(func.sum(Invoice.amount), 0.0),
        ).where(Invoice.status == "unpaid")
    ).one()
    overdue_count = db.scalar(
        select(func.count(Invoice.id)).where(
            Invoice.status == "unpaid",
            Invoice.days_overdue > 0,
        )
    )

    return {
        "invoice_count": invoice_count,
        "total_billed": _json_amount(float(total_billed)),
        "unpaid_count": unpaid_count,
        "total_unpaid": _json_amount(float(total_unpaid)),
        "overdue_count": overdue_count,
    }


@router.post("/reminders/draft/{invoice_id}")
def create_payment_reminder(invoice_id: str, db: DbSession):
    invoice, customer = _get_reminder_data(db, invoice_id)
    amount = _json_amount(invoice.amount)

    return {
        "invoice_id": invoice_id,
        "to": customer.email,
        "subject": f"Relance facture {invoice_id}",
        "body": (
            f"Bonjour {customer.name}, "
            f"la facture {invoice_id} d'un montant de "
            f"{amount} € présente un retard de "
            f"{invoice.days_overdue} jours."
        ),
        "status": "draft",
    }


@router.post("/reminders/send/{invoice_id}")
def send_payment_reminder(invoice_id: str, db: DbSession):
    _, customer = _get_reminder_data(db, invoice_id)

    print(f"SEND EXECUTED -> {customer.email} / facture {invoice_id}")

    return {
        "invoice_id": invoice_id,
        "to": customer.email,
        "status": "sent_simulated",
    }
