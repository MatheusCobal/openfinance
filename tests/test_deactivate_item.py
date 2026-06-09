"""Tests for POST /sync/items/{item_id}/deactivate."""

import unittest
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import Account, Item, Transaction
from app.services.transactions import bank_outflow_transactions


def _make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


class DeactivateItemEndpointTest(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_get_session
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def _seed(self, item_id: str, account_ids: list[str]) -> None:
        with Session(self.engine) as session:
            session.add(
                Item(
                    id=item_id,
                    connector_id=1,
                    connector_name="Test",
                    status="UPDATED",
                    is_active=True,
                )
            )
            for acc_id in account_ids:
                session.add(
                    Account(id=acc_id, item_id=item_id, name=acc_id, type="BANK", is_active=True)
                )
            session.commit()

    def test_deactivates_item_and_all_accounts(self):
        self._seed("item-1", ["acc-a", "acc-b"])

        resp = self.client.post("/sync/items/item-1/deactivate")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["item_id"], "item-1")
        self.assertTrue(data["deactivated_item"])
        self.assertEqual(data["deactivated_accounts"], 2)

        with Session(self.engine) as session:
            item = session.get(Item, "item-1")
            acc_a = session.get(Account, "acc-a")
            acc_b = session.get(Account, "acc-b")

        self.assertFalse(item.is_active)
        self.assertIsNotNone(item.deactivated_at)
        self.assertFalse(acc_a.is_active)
        self.assertIsNotNone(acc_a.deactivated_at)
        self.assertFalse(acc_b.is_active)
        self.assertIsNotNone(acc_b.deactivated_at)

    def test_returns_404_for_unknown_item(self):
        resp = self.client.post("/sync/items/nonexistent/deactivate")
        self.assertEqual(resp.status_code, 404)

    def test_deactivate_with_no_accounts_returns_zero(self):
        with Session(self.engine) as session:
            session.add(
                Item(
                    id="item-empty",
                    connector_id=1,
                    connector_name="Test",
                    status="UPDATED",
                    is_active=True,
                )
            )
            session.commit()

        resp = self.client.post("/sync/items/item-empty/deactivate")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["deactivated_accounts"], 0)

    def test_bank_outflow_excludes_deactivated_item_accounts(self):
        today = date.today()
        self._seed("item-caixa", ["bank-caixa"])

        with Session(self.engine) as session:
            session.add(
                Item(
                    id="item-itau",
                    connector_id=2,
                    connector_name="Itau",
                    status="UPDATED",
                    is_active=True,
                )
            )
            session.add(
                Account(
                    id="bank-itau", item_id="item-itau", name="Itau", type="BANK", is_active=True
                )
            )
            session.add(
                Transaction(
                    id="tx-itau",
                    account_id="bank-itau",
                    date=today,
                    amount=Decimal("-100"),
                    description="Pix Itau",
                    category="Transfers",
                )
            )
            session.add(
                Transaction(
                    id="tx-caixa",
                    account_id="bank-caixa",
                    date=today,
                    amount=Decimal("-3000"),
                    description="Pix Caixa",
                    category="Transfers",
                )
            )
            session.commit()

        # Deactivate CAIXA item via the endpoint
        resp = self.client.post("/sync/items/item-caixa/deactivate")
        self.assertEqual(resp.status_code, 200)

        with Session(self.engine) as session:
            txs = bank_outflow_transactions(session, today, today)

        ids = {tx.id for tx in txs}
        self.assertIn("tx-itau", ids)
        self.assertNotIn("tx-caixa", ids)
        total = sum(abs(tx.amount) for tx in txs)
        self.assertEqual(total, Decimal("100"))


if __name__ == "__main__":
    unittest.main()
