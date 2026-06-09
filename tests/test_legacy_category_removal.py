import unittest

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import Account, Item, Transaction
from app.services.sync import upsert_transaction


class LegacyCategoryRemovalTest(unittest.TestCase):
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

    def test_legacy_category_routes_return_gone(self):
        for path in (
            "/categories",
            "/category-rules/description",
            "/category-rules/description/suggestions",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 410, path)

        response = self.client.get("/transactions", params={"category_id": 1})
        self.assertEqual(response.status_code, 410)

    def test_variable_budget_progress_is_empty(self):
        response = self.client.get("/budgets/progress", params={"year_month": "2026-06"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["legacy_category_budget_removed"])
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["summary"]["target"], 0.0)

    def test_sync_preserves_raw_pluggy_category(self):
        with Session(self.engine) as session:
            session.add(
                Item(
                    id="item-1",
                    connector_id=1,
                    status="UPDATED",
                    is_active=True,
                )
            )
            session.add(
                Account(
                    id="acc-1",
                    item_id="item-1",
                    name="Card",
                    type="CREDIT",
                    is_active=True,
                )
            )
            session.commit()

            upsert_transaction(
                {
                    "id": "tx-1",
                    "date": "2026-06-09",
                    "amount": "-42.50",
                    "description": "Lunch",
                    "category": "Food delivery",
                    "currencyCode": "BRL",
                },
                "acc-1",
                session,
            )
            session.commit()
            tx = session.get(Transaction, "tx-1")

        self.assertIsNotNone(tx)
        self.assertEqual(tx.category, "Food delivery")
        self.assertEqual(tx.pluggy_raw_category, "Food delivery")
        self.assertEqual(tx.internal_category, "Alimentação")
        self.assertEqual(tx.cashflow_type, "expense")
        self.assertEqual(tx.classification_source, "pluggy_rule")


if __name__ == "__main__":
    unittest.main()
