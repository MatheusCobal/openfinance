import datetime
import unittest
from decimal import Decimal

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import Account, CreditCardBill, Item
from fastapi.testclient import TestClient

_ITEM_ID = "item-test"


def _seed_item(session: Session) -> None:
    if not session.get(Item, _ITEM_ID):
        session.add(Item(id=_ITEM_ID, connector_id=1, connector_name="Test", status="UPDATED"))
        session.commit()


class CreditCardDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_get_session
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_empty_db_returns_200(self):
        response = self.client.get("/dashboard/credit-card-diagnostics?year_month=2026-05")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["year_month"], "2026-05")
        self.assertEqual(body["credit_account_count"], 0)
        self.assertEqual(body["bills_for_month_count"], 0)
        self.assertEqual(body["fallback_reason"], "no_credit_accounts")
        self.assertEqual(body["source"], "transaction_fallback")

    def test_credit_account_without_balance(self):
        with Session(self.engine) as session:
            _seed_item(session)
            session.add(Account(
                id="cc-1", item_id=_ITEM_ID, name="Visa", type="CREDIT",
                balance=None, currency_code="BRL",
            ))
            session.commit()

        response = self.client.get("/dashboard/credit-card-diagnostics?year_month=2026-05")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["credit_account_count"], 1)
        self.assertEqual(body["credit_accounts_with_balance_count"], 0)
        self.assertEqual(body["fallback_reason"], "credit_accounts_without_balance")

    def test_credit_account_with_balance(self):
        with Session(self.engine) as session:
            _seed_item(session)
            session.add(Account(
                id="cc-1", item_id=_ITEM_ID, name="Visa", type="CREDIT",
                balance=Decimal("1200.00"), currency_code="BRL",
            ))
            session.commit()

        response = self.client.get("/dashboard/credit-card-diagnostics?year_month=2026-05")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["credit_accounts_with_balance_count"], 1)
        self.assertEqual(body["fallback_reason"], "account_balance_available")
        self.assertEqual(body["source"], "account_balance")

    def test_bill_due_in_month(self):
        with Session(self.engine) as session:
            _seed_item(session)
            session.add(Account(
                id="cc-1", item_id=_ITEM_ID, name="Visa", type="CREDIT",
                balance=None, currency_code="BRL",
            ))
            session.add(CreditCardBill(
                id="bill-1", account_id="cc-1",
                due_date=datetime.date(2026, 5, 15),
                total_amount=Decimal("980.00"),
            ))
            session.commit()

        response = self.client.get("/dashboard/credit-card-diagnostics?year_month=2026-05")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["bills_for_month_count"], 1)
        self.assertEqual(body["fallback_reason"], "bill_available")
        self.assertEqual(body["source"], "bill")
        self.assertEqual(body["bills_for_month"][0]["total_amount"], 980.0)


if __name__ == "__main__":
    unittest.main()
