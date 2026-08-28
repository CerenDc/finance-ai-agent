from sqlalchemy import select

from app.db.database import Base, SessionLocal, engine
from app.db.models import Customer, Invoice


CUSTOMERS = [
    Customer(id=1, name="TechNova", email="finance@technova.fr"),
    Customer(id=2, name="GreenCorp", email="compta@greencorp.fr"),
    Customer(id=3, name="DataVision", email="accounting@datavision.fr"),
]

INVOICES = [
    Invoice(id="INV-001", customer_id=1, amount=4500.0, status="unpaid", days_overdue=45),
    Invoice(id="INV-002", customer_id=2, amount=2200.0, status="paid", days_overdue=0),
    Invoice(id="INV-003", customer_id=3, amount=7800.0, status="unpaid", days_overdue=12),
    Invoice(id="INV-004", customer_id=1, amount=1300.0, status="unpaid", days_overdue=70),
]


def seed_database() -> None:
    Base.metadata.create_all(bind=engine)

    with SessionLocal.begin() as session:
        existing_customer_ids = set(session.scalars(select(Customer.id)).all())
        existing_invoice_ids = set(session.scalars(select(Invoice.id)).all())

        session.add_all(
            customer
            for customer in CUSTOMERS
            if customer.id not in existing_customer_ids
        )
        session.add_all(
            invoice
            for invoice in INVOICES
            if invoice.id not in existing_invoice_ids
        )


if __name__ == "__main__":
    seed_database()
    print("Finance database seeded successfully.")
