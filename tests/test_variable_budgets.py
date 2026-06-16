"""Tests for the 10D-C variable budget goals (Metas variáveis).

Financial rules under test (mirroring the standardized card sign convention):
  - only real CREDIT purchases count as spend;
  - invoice payments, refunds/cancellations, transfers and income never inflate
    the spend, and abs() is never used to flip a negative row into spending;
  - goals are independent per month and grouped by the Pluggy-based category
    labels (same grouping as the dashboard "gastos por categoria").
"""

import datetime
import unittest
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import Account, Item, Transaction
from app.services.fixed_costs import _month_bounds
from app.services.variable_budgets import upsert_goal, variable_budget_progress

ITEM_ID = "item-1"
CC_ID = "cc-1"
BANK_ID = "bank-1"
YEAR_MONTH = "2026-06"
TODAY = datetime.date(2026, 6, 12)


def _make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _seed_accounts(session: Session) -> None:
    session.add(Item(id=ITEM_ID, connector_id=1, connector_name="T", status="UPDATED"))
    session.add(
        Account(
            id=CC_ID, item_id=ITEM_ID, name="Card", type="CREDIT",
            currency_code="BRL", is_active=True,
        )
    )
    session.add(
        Account(
            id=BANK_ID, item_id=ITEM_ID, name="Checking", type="BANK",
            currency_code="BRL", is_active=True,
        )
    )
    session.commit()


def _add_tx(session, tx_id, amount, description, category, account_id=CC_ID, day=10):
    session.add(
        Transaction(
            id=tx_id,
            account_id=account_id,
            date=datetime.date(2026, 6, day),
            amount=Decimal(amount),
            description=description,
            category=category,
        )
    )
    session.commit()


def _progress(session):
    first_day, last_day = _month_bounds(YEAR_MONTH)
    return variable_budget_progress(
        session, YEAR_MONTH, first_day, last_day, TODAY, exclude_transaction_ids=set()
    )


def _item(payload, category):
    for item in payload["items"]:
        if item["category"] == category:
            return item
    return None


class VariableBudgetServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def test_empty_month_is_honest_empty_state(self):
        with Session(self.engine) as session:
            _seed_accounts(session)
            payload = _progress(session)
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["summary"]["target"], 0.0)
        self.assertEqual(payload["summary"]["actual_spent"], 0.0)
        self.assertEqual(payload["summary"]["goal_count"], 0)

    def test_goal_with_credit_purchase(self):
        with Session(self.engine) as session:
            _seed_accounts(session)
            upsert_goal(session, YEAR_MONTH, "Alimentação", 500)
            _add_tx(session, "buy-1", "200.00", "Mercado", "Groceries")
            payload = _progress(session)
            item = _item(payload, "Alimentação")
        self.assertIsNotNone(item)
        self.assertEqual(item["target"], 500.0)
        self.assertEqual(item["spent"], 200.0)
        self.assertEqual(item["remaining"], 300.0)
        self.assertEqual(item["progress_percent"], 40.0)
        self.assertEqual(item["status"], "ok")
        self.assertTrue(item["has_target"])
        self.assertEqual(item["transaction_count"], 1)
        summary = payload["summary"]
        self.assertEqual(summary["target"], 500.0)
        self.assertEqual(summary["actual_spent"], 200.0)
        self.assertEqual(summary["target_consumed"], 200.0)
        self.assertEqual(summary["target_remaining"], 300.0)
        self.assertEqual(summary["target_overage"], 0.0)

    def test_invoice_payment_and_refund_do_not_inflate_spend(self):
        with Session(self.engine) as session:
            _seed_accounts(session)
            upsert_goal(session, YEAR_MONTH, "Alimentação", 500)
            _add_tx(session, "buy-1", "200.00", "Mercado", "Groceries")
            _add_tx(session, "refund-1", "-50.00", "CANC PARCELA", "Groceries")
            _add_tx(session, "pay-1", "-1500.00", "Pagamento recebido", "Credit card payment")
            payload = _progress(session)
            item = _item(payload, "Alimentação")
        # 200 purchase - 50 refund = 150; payment is never counted.
        self.assertEqual(item["spent"], 150.0)
        self.assertEqual(item["transaction_count"], 1)

    def test_refund_only_category_floors_at_zero(self):
        with Session(self.engine) as session:
            _seed_accounts(session)
            upsert_goal(session, YEAR_MONTH, "Outros", 300)
            _add_tx(session, "canc-1", "-100.00", "Estorno compra", "Shopping")
            payload = _progress(session)
            item = _item(payload, "Outros")
        self.assertEqual(item["spent"], 0.0)
        self.assertEqual(item["transaction_count"], 0)

    def test_bank_spending_is_not_counted(self):
        with Session(self.engine) as session:
            _seed_accounts(session)
            upsert_goal(session, YEAR_MONTH, "Alimentação", 500)
            # BANK outflow + BANK income in a food-like description: must be ignored.
            _add_tx(session, "bank-out", "-80.00", "Mercado", "Groceries", account_id=BANK_ID)
            _add_tx(session, "bank-in", "5000.00", "Salario", "Salary", account_id=BANK_ID)
            payload = _progress(session)
            item = _item(payload, "Alimentação")
        self.assertEqual(item["spent"], 0.0)
        self.assertEqual(payload["summary"]["actual_spent"], 0.0)

    def test_goal_without_spend_shows_zero(self):
        with Session(self.engine) as session:
            _seed_accounts(session)
            upsert_goal(session, YEAR_MONTH, "Transporte", 200)
            payload = _progress(session)
            item = _item(payload, "Transporte")
        self.assertIsNotNone(item)
        self.assertEqual(item["spent"], 0.0)
        self.assertEqual(item["remaining"], 200.0)
        self.assertTrue(item["has_target"])

    def test_spend_without_goal_is_suggestion(self):
        with Session(self.engine) as session:
            _seed_accounts(session)
            _add_tx(session, "buy-1", "75.00", "Uber", "Transport")
            payload = _progress(session)
            item = _item(payload, "Transporte")
        self.assertIsNotNone(item)
        self.assertFalse(item["has_target"])
        self.assertEqual(item["status"], "no_target")
        self.assertEqual(item["spent"], 75.0)
        self.assertEqual(payload["summary"]["unbudgeted_count"], 1)
        self.assertEqual(payload["summary"]["target"], 0.0)

    def test_overage_when_spent_exceeds_target(self):
        with Session(self.engine) as session:
            _seed_accounts(session)
            upsert_goal(session, YEAR_MONTH, "Alimentação", 100)
            _add_tx(session, "buy-1", "180.00", "Mercado", "Groceries")
            payload = _progress(session)
            item = _item(payload, "Alimentação")
        self.assertEqual(item["spent"], 180.0)
        self.assertEqual(item["remaining"], -80.0)
        self.assertEqual(item["status"], "over")
        summary = payload["summary"]
        self.assertEqual(summary["target_overage"], 80.0)
        self.assertEqual(summary["target_consumed"], 100.0)
        self.assertEqual(summary["target_remaining"], 0.0)

    def test_sum_of_goals_drives_total_target(self):
        with Session(self.engine) as session:
            _seed_accounts(session)
            upsert_goal(session, YEAR_MONTH, "Alimentação", 500)
            upsert_goal(session, YEAR_MONTH, "Transporte", 250)
            payload = _progress(session)
        self.assertEqual(payload["summary"]["target"], 750.0)
        self.assertEqual(payload["summary"]["goal_count"], 2)

    def test_goals_are_independent_per_month(self):
        with Session(self.engine) as session:
            _seed_accounts(session)
            upsert_goal(session, YEAR_MONTH, "Alimentação", 500)
            first_day, last_day = _month_bounds("2026-07")
            payload = variable_budget_progress(
                session, "2026-07", first_day, last_day,
                datetime.date(2026, 7, 12), exclude_transaction_ids=set(),
            )
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["summary"]["target"], 0.0)


class VariableBudgetApiTest(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_get_session
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_upsert_get_and_delete_flow(self):
        put = self.client.put(
            "/budgets/variable",
            json={"year_month": YEAR_MONTH, "category": "Alimentação", "target_amount": 500},
        )
        self.assertEqual(put.status_code, 200)
        self.assertEqual(put.json()["target_amount"], 500.0)

        progress = self.client.get("/budgets/progress", params={"year_month": YEAR_MONTH})
        self.assertEqual(progress.status_code, 200)
        body = progress.json()
        self.assertEqual(body["summary"]["target"], 500.0)
        item = _item(body, "Alimentação")
        self.assertIsNotNone(item)
        for key in (
            "category", "target", "spent", "remaining",
            "progress_percent", "status", "transaction_count",
        ):
            self.assertIn(key, item)

        # Update (upsert) the same goal.
        put2 = self.client.put(
            "/budgets/variable",
            json={"year_month": YEAR_MONTH, "category": "Alimentação", "target_amount": 800},
        )
        self.assertEqual(put2.status_code, 200)
        self.assertEqual(put2.json()["target_amount"], 800.0)

        deleted = self.client.delete(
            "/budgets/variable",
            params={"year_month": YEAR_MONTH, "category": "Alimentação"},
        )
        self.assertEqual(deleted.status_code, 200)
        after = self.client.get("/budgets/progress", params={"year_month": YEAR_MONTH})
        self.assertEqual(after.json()["summary"]["target"], 0.0)

    def test_eligible_categories_endpoint(self):
        response = self.client.get("/budgets/variable/categories")
        self.assertEqual(response.status_code, 200)
        categories = response.json()["categories"]
        self.assertIn("Alimentação", categories)
        self.assertIn("Outros", categories)
        self.assertNotIn("Compras pessoais", categories)
        self.assertNotIn("Outros / Taxas", categories)
        self.assertEqual(len(categories), 9)

    def test_validation_rejects_negative_target(self):
        response = self.client.put(
            "/budgets/variable",
            json={"year_month": YEAR_MONTH, "category": "Alimentação", "target_amount": -10},
        )
        self.assertEqual(response.status_code, 400)

    def test_validation_rejects_unknown_category(self):
        response = self.client.put(
            "/budgets/variable",
            json={"year_month": YEAR_MONTH, "category": "Cassino", "target_amount": 100},
        )
        self.assertEqual(response.status_code, 400)

    def test_delete_missing_goal_returns_404(self):
        response = self.client.delete(
            "/budgets/variable",
            params={"year_month": YEAR_MONTH, "category": "Transporte"},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
