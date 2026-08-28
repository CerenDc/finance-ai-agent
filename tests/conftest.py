import os
from collections.abc import Iterator

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("LANGGRAPH_POSTGRES_URI", "postgresql://unused:unused@localhost/unused")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import Customer, Invoice
from app.main import app


class FakeFinanceGraph:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict]] = []
        self.error: Exception | None = None

    async def ainvoke(self, value: object, config: dict) -> dict:
        self.calls.append((value, config))
        if self.error is not None:
            raise self.error

        resume = getattr(value, "resume", None)
        if resume is not None:
            status = "sent_simulated" if resume == "approve" else "cancelled"
            return {"messages": [AIMessage(content=f"Relance: {status}")]}

        messages = value["messages"]
        question = messages[-1].content
        if "Envoie une relance" in question:
            from types import SimpleNamespace

            return {
                "messages": messages,
                "__interrupt__": [
                    SimpleNamespace(
                        value={
                            "message": "Approuver l'envoi ?",
                            "invoice_id": "INV-001",
                            "destinataire": "finance@technova.fr",
                            "subject": "Relance facture INV-001",
                            "body": "Brouillon",
                        }
                    )
                ],
            }

        return {
            "messages": [
                *messages,
                AIMessage(content="TechNova nous doit 5 800 € sur 2 factures."),
            ]
        }


@pytest.fixture
def db_session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add_all(
            [
                Customer(id=1, name="TechNova", email="finance@technova.fr"),
                Customer(id=2, name="GreenCorp", email="compta@greencorp.fr"),
            ]
        )
        session.add_all(
            [
                Invoice(
                    id="INV-001",
                    customer_id=1,
                    amount=4500,
                    status="unpaid",
                    days_overdue=45,
                ),
                Invoice(
                    id="INV-004",
                    customer_id=1,
                    amount=1300,
                    status="unpaid",
                    days_overdue=70,
                ),
                Invoice(
                    id="INV-002",
                    customer_id=2,
                    amount=2200,
                    status="paid",
                    days_overdue=0,
                ),
            ]
        )

    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def fake_graph() -> FakeFinanceGraph:
    return FakeFinanceGraph()


@pytest.fixture
def api_client(
    db_session_factory: sessionmaker[Session],
    fake_graph: FakeFinanceGraph,
) -> Iterator[TestClient]:
    def override_get_db() -> Iterator[Session]:
        with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.state.finance_graph = fake_graph
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    client.close()
    app.dependency_overrides.clear()

