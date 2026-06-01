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
        # No credit-card data at all → source "none".
        self.assertEqual(body["source"], "none")

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
        # 2026-05 is a past month relative to the current date. A current
        # Account.balance snapshot is NOT a valid past-month invoice source, so
        # the planning invoice resolves to "none" (no bill, no transactions).
        self.assertEqual(body["source"], "none")
        self.assertEqual(body["planning_invoice"]["source"], "none")

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
        # Official CreditCardBill wins for a past/future month.
        self.assertEqual(body["source"], "official_bill")
        self.assertEqual(body["bills_for_month"][0]["total_amount"], 980.0)


class CreditCardInvoiceRouteTest(unittest.TestCase):
    """GET /credit-card/invoice/{year_month} → planning_invoice_for_month()."""

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

    def test_route_returns_planning_invoice_shape(self):
        with Session(self.engine) as session:
            _seed_item(session)
            session.add(Account(
                id="cc-1", item_id=_ITEM_ID, name="Visa", type="CREDIT",
                balance=Decimal("1200.00"), currency_code="BRL",
                credit_balance_due_date=datetime.date(2026, 5, 17),
            ))
            session.commit()

        response = self.client.get("/credit-card/invoice/2026-05")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        for key in (
            "year_month", "amount", "source", "source_label", "is_estimated",
            "due_dates", "cards", "transaction_count", "bill_count",
            "account_count", "cycle_start", "cycle_end",
        ):
            self.assertIn(key, body)
        self.assertEqual(body["year_month"], "2026-05")

    def test_route_rejects_invalid_month(self):
        self.assertEqual(
            self.client.get("/credit-card/invoice/not-a-month").status_code, 400
        )


class PlanningRouteTest(unittest.TestCase):
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

    def test_planning_month_returns_frontend_friendly_shape(self):
        response = self.client.get("/planning/month/2026-05")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["year_month"], "2026-05")
        for key in (
            "income",
            "fixed_costs",
            "variable_budgets",
            "credit_card_invoice",
            "capacity",
            "raw",
        ):
            self.assertIn(key, body)
        self.assertIn("spending_capacity", body["raw"])

    def test_planning_month_rejects_invalid_year_month(self):
        response = self.client.get("/planning/month/2026-13")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
