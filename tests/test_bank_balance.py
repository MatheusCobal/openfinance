import unittest
from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import Account, Item
from app.services.bank_balance import bank_balance_summary


class BankBalanceSummaryTest(unittest.TestCase):
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

    def _add_item(self, session, item_id="item-1", active=True):
        session.add(Item(id=item_id, connector_id=1, status="UPDATED", is_active=active))

    def _add_bank_account(
        self,
        session,
        *,
        account_id="bank-1",
        item_id="item-1",
        balance=Decimal("5000"),
        updated_at=None,
        active=True,
    ):
        session.add(
            Account(
                id=account_id,
                item_id=item_id,
                name="Conta corrente",
                type="BANK",
                balance=balance,
                balance_updated_at=updated_at or datetime(2026, 6, 8, 18, 37),
                is_active=active,
            )
        )

    def _add_credit_account(self, session, account_id="credit-1", item_id="item-1"):
        session.add(
            Account(
                id=account_id,
                item_id=item_id,
                name="Cartão Itaú",
                type="CREDIT",
                balance=Decimal("1000"),
                is_active=True,
            )
        )

    # ── service tests ─────────────────────────────────────────────────────────

    def test_sums_active_bank_accounts(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_bank_account(session, account_id="bank-1", balance=Decimal("3000"))
            self._add_bank_account(session, account_id="bank-2", balance=Decimal("2000"))
            session.commit()

        with Session(self.engine) as session:
            result = bank_balance_summary(session)

        self.assertAlmostEqual(result["total"], 5000.0, places=2)
        self.assertEqual(result["account_count"], 2)
        self.assertEqual(result["source"], "active_bank_accounts")

    def test_excludes_credit_accounts(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_bank_account(session, balance=Decimal("1000"))
            self._add_credit_account(session)
            session.commit()

        with Session(self.engine) as session:
            result = bank_balance_summary(session)

        self.assertAlmostEqual(result["total"], 1000.0, places=2)
        self.assertEqual(result["account_count"], 1)
        ids = [a["id"] for a in result["accounts"]]
        self.assertNotIn("credit-1", ids)

    def test_excludes_inactive_bank_accounts(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_bank_account(session, account_id="bank-active", balance=Decimal("4000"))
            self._add_bank_account(
                session,
                account_id="bank-inactive",
                balance=Decimal("9999"),
                active=False,
            )
            session.commit()

        with Session(self.engine) as session:
            result = bank_balance_summary(session)

        self.assertAlmostEqual(result["total"], 4000.0, places=2)
        self.assertEqual(result["account_count"], 1)

    def test_excludes_accounts_of_inactive_items(self):
        with Session(self.engine) as session:
            self._add_item(session, item_id="item-active", active=True)
            self._add_item(session, item_id="item-inactive", active=False)
            self._add_bank_account(
                session, account_id="bank-ok", item_id="item-active", balance=Decimal("500")
            )
            self._add_bank_account(
                session,
                account_id="bank-dead-item",
                item_id="item-inactive",
                balance=Decimal("9999"),
            )
            session.commit()

        with Session(self.engine) as session:
            result = bank_balance_summary(session)

        self.assertAlmostEqual(result["total"], 500.0, places=2)
        self.assertEqual(result["account_count"], 1)

    def test_treats_balance_none_as_zero(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_bank_account(session, account_id="bank-known", balance=Decimal("1200"))
            session.add(
                Account(
                    id="bank-no-balance",
                    item_id="item-1",
                    name="Conta sem saldo",
                    type="BANK",
                    balance=None,
                    is_active=True,
                )
            )
            session.commit()

        with Session(self.engine) as session:
            result = bank_balance_summary(session)

        self.assertAlmostEqual(result["total"], 1200.0, places=2)
        self.assertEqual(result["account_count"], 2)
        no_bal = next(a for a in result["accounts"] if a["id"] == "bank-no-balance")
        self.assertIsNone(no_bal["balance"])

    def test_returns_account_list(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_bank_account(session, balance=Decimal("750"))
            session.commit()

        with Session(self.engine) as session:
            result = bank_balance_summary(session)

        self.assertEqual(len(result["accounts"]), 1)
        self.assertEqual(result["accounts"][0]["id"], "bank-1")
        self.assertAlmostEqual(result["accounts"][0]["balance"], 750.0, places=2)

    def test_returns_most_recent_updated_at(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_bank_account(
                session,
                account_id="bank-old",
                balance=Decimal("100"),
                updated_at=datetime(2026, 6, 1, 10, 0),
            )
            self._add_bank_account(
                session,
                account_id="bank-new",
                balance=Decimal("200"),
                updated_at=datetime(2026, 6, 8, 18, 37),
            )
            session.commit()

        with Session(self.engine) as session:
            result = bank_balance_summary(session)

        self.assertIn("2026-06-08", result["updated_at"])

    def test_empty_returns_zero_total(self):
        with Session(self.engine) as session:
            result = bank_balance_summary(session)

        self.assertEqual(result["total"], 0.0)
        self.assertEqual(result["account_count"], 0)
        self.assertIsNone(result["updated_at"])
        self.assertEqual(result["accounts"], [])

    # ── endpoint test ─────────────────────────────────────────────────────────

    def test_endpoint_returns_bank_balance_summary(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_bank_account(session, balance=Decimal("3500"))
            session.commit()

        response = self.client.get("/bank/balance-summary")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertAlmostEqual(data["total"], 3500.0, places=2)
        self.assertEqual(data["account_count"], 1)
        self.assertEqual(data["source"], "active_bank_accounts")
        self.assertIn("accounts", data)
        self.assertIn("updated_at", data)


if __name__ == "__main__":
    unittest.main()
