"""Tests for active/inactive lifecycle on Item and Account.

Verifies that inactive Items/Accounts are excluded from current
planning/cashflow/snapshot calculations.
"""

import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.main import app
from app.models import Account, CreditCardBill, Investment, Item, Transaction
from app.services import sync as sync_service
from app.services.credit_card_invoice import planning_invoice_for_month
from app.services.pluggy_snapshot import account_snapshot_summary
from app.services.transactions import (
    account_ids_by_type,
    bank_outflow_transactions,
)


def _make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _seed_item(session: Session, item_id: str, is_active: bool = True) -> Item:
    item = Item(id=item_id, connector_id=1, connector_name="Test", status="UPDATED",
                is_active=is_active)
    session.add(item)
    session.commit()
    return item


def _seed_account(
    session: Session,
    account_id: str,
    item_id: str,
    account_type: str = "BANK",
    is_active: bool = True,
    balance: Decimal = Decimal("0"),
) -> Account:
    account = Account(
        id=account_id,
        item_id=item_id,
        name=f"Account {account_id}",
        type=account_type,
        is_active=is_active,
        balance=balance,
    )
    session.add(account)
    session.commit()
    return account


class AccountIdsByTypeFilterTest(unittest.TestCase):
    """Test 1: account_ids_by_type active filter."""

    def setUp(self):
        self.engine = _make_engine()

    def test_active_only_excludes_inactive(self):
        with Session(self.engine) as session:
            _seed_item(session, "item-a", is_active=True)
            _seed_item(session, "item-b", is_active=True)
            _seed_account(session, "bank-active", "item-a", "BANK", is_active=True)
            _seed_account(session, "bank-inactive", "item-b", "BANK", is_active=False)

            active_ids = account_ids_by_type(session, {"BANK"}, active_only=True)
            all_ids = account_ids_by_type(session, {"BANK"}, active_only=False)

        self.assertEqual(active_ids, ["bank-active"])
        self.assertIn("bank-active", all_ids)
        self.assertIn("bank-inactive", all_ids)

    def test_inactive_item_excludes_its_accounts(self):
        with Session(self.engine) as session:
            _seed_item(session, "item-active", is_active=True)
            _seed_item(session, "item-inactive", is_active=False)
            _seed_account(session, "bank-ok", "item-active", "BANK", is_active=True)
            _seed_account(session, "bank-dead", "item-inactive", "BANK", is_active=True)

            active_ids = account_ids_by_type(session, {"BANK"}, active_only=True)
            all_ids = account_ids_by_type(session, {"BANK"}, active_only=False)

        self.assertEqual(active_ids, ["bank-ok"])
        self.assertIn("bank-dead", all_ids)


class BankOutflowExcludesInactiveTest(unittest.TestCase):
    """Test 2: bank_outflow_transactions excludes inactive bank accounts."""

    def setUp(self):
        self.engine = _make_engine()

    def test_outflow_from_inactive_account_excluded(self):
        today = date.today()
        with Session(self.engine) as session:
            _seed_item(session, "item-itau", is_active=True)
            _seed_item(session, "item-caixa", is_active=False)
            _seed_account(session, "bank-itau", "item-itau", "BANK", is_active=True)
            _seed_account(session, "bank-caixa", "item-caixa", "BANK", is_active=False)

            session.add(Transaction(
                id="tx-itau-out",
                account_id="bank-itau",
                date=today,
                amount=Decimal("-100"),
                description="Pix enviado Itau",
                category="Transfers",
            ))
            session.add(Transaction(
                id="tx-caixa-out",
                account_id="bank-caixa",
                date=today,
                amount=Decimal("-3000"),
                description="Pix enviado Caixa",
                category="Transfers",
            ))
            session.commit()

            txs = bank_outflow_transactions(session, today, today)
            total = sum(abs(tx.amount) for tx in txs)

        ids = {tx.id for tx in txs}
        self.assertIn("tx-itau-out", ids)
        self.assertNotIn("tx-caixa-out", ids)
        self.assertEqual(total, Decimal("100"))


class AccountSnapshotExcludesInactiveTest(unittest.TestCase):
    """Test 3: account_snapshot_summary excludes inactive accounts."""

    def setUp(self):
        self.engine = _make_engine()

    def test_bank_total_excludes_inactive_account(self):
        with Session(self.engine) as session:
            _seed_item(session, "item-active", is_active=True)
            _seed_item(session, "item-inactive", is_active=False)
            _seed_account(session, "bank-ok", "item-active", "BANK",
                          is_active=True, balance=Decimal("1000"))
            _seed_account(session, "bank-dead", "item-inactive", "BANK",
                          is_active=False, balance=Decimal("5000"))

            summary = account_snapshot_summary(session)

        self.assertEqual(summary["bank"]["total"], 1000.0)
        self.assertEqual(summary["bank"]["account_count"], 1)


class CreditObligationExcludesInactiveTest(unittest.TestCase):
    """Test 4 & 5: planning_invoice_for_month excludes inactive accounts/bills."""

    def setUp(self):
        self.engine = _make_engine()

    def test_account_balance_tier_excludes_inactive(self):
        # account_balance is the current-month fallback (no cycle txs, no bill).
        # Pin today inside the queried month so it resolves as the current month.
        today = date(2026, 5, 15)
        with Session(self.engine) as session:
            _seed_item(session, "item-active", is_active=True)
            _seed_item(session, "item-inactive", is_active=False)
            _seed_account(session, "cc-active", "item-active", "CREDIT",
                          is_active=True, balance=Decimal("1000"))
            _seed_account(session, "cc-inactive", "item-inactive", "CREDIT",
                          is_active=False, balance=Decimal("5000"))

            result = planning_invoice_for_month(session, "2026-05", today=today)

        self.assertEqual(result["source"], "account_balance")
        self.assertEqual(result["amount"], 1000.0)

    def test_bill_tier_excludes_bills_from_inactive_accounts(self):
        # official_bill is used for future/past months. Pin today before the
        # queried month so 2026-05 is a future month (bill tier).
        today = date(2026, 4, 1)
        with Session(self.engine) as session:
            _seed_item(session, "item-active", is_active=True)
            _seed_item(session, "item-inactive", is_active=False)
            _seed_account(session, "cc-active", "item-active", "CREDIT",
                          is_active=True, balance=Decimal("1000"))
            _seed_account(session, "cc-inactive", "item-inactive", "CREDIT",
                          is_active=False, balance=Decimal("5000"))

            session.add(CreditCardBill(
                id="bill-active",
                account_id="cc-active",
                due_date=date(2026, 5, 15),
                total_amount=Decimal("1000"),
            ))
            session.add(CreditCardBill(
                id="bill-inactive",
                account_id="cc-inactive",
                due_date=date(2026, 5, 20),
                total_amount=Decimal("5000"),
            ))
            session.commit()

            result = planning_invoice_for_month(session, "2026-05", today=today)

        self.assertEqual(result["source"], "official_bill")
        self.assertEqual(result["amount"], 1000.0)
        account_ids_in_result = {c["account_id"] for c in result["cards"]}
        self.assertIn("cc-active", account_ids_in_result)
        self.assertNotIn("cc-inactive", account_ids_in_result)


class SyncDeactivatesMissingAccountsTest(unittest.TestCase):
    """Test 6: sync deactivates accounts no longer returned by Pluggy."""

    def setUp(self):
        self.engine = _make_engine()
        self.original_pluggy = sync_service.pluggy

    def tearDown(self):
        sync_service.pluggy = self.original_pluggy

    def test_missing_account_deactivated_after_sync(self):
        class FakePluggyTwoAccounts:
            def get_item(self, item_id):
                return {"id": item_id, "connector": {"id": 1, "name": "Fake"}, "status": "UPDATED"}

            def list_accounts(self, item_id):
                return [
                    {"id": "acc-a", "name": "Account A", "type": "BANK"},
                    {"id": "acc-b", "name": "Account B", "type": "BANK"},
                ]

            def list_transactions(self, account_id, from_date=None, bill_id=None):
                return []

            def list_investments(self, item_id):
                raise Exception("no investments")

        sync_service.pluggy = FakePluggyTwoAccounts()

        with Session(self.engine) as session:
            _seed_item(session, "item-1", is_active=True)
            _seed_account(session, "acc-a", "item-1", "BANK", is_active=True)
            _seed_account(session, "acc-b", "item-1", "BANK", is_active=True)

            # Now simulate Pluggy returning only acc-a
            class FakePluggyOneAccount:
                def get_item(self, item_id):
                    return {"id": item_id, "connector": {"id": 1, "name": "Fake"}, "status": "UPDATED"}

                def list_accounts(self, item_id):
                    return [{"id": "acc-a", "name": "Account A", "type": "BANK"}]

                def list_transactions(self, account_id, from_date=None, bill_id=None):
                    return []

                def list_investments(self, item_id):
                    raise Exception("no investments")

            sync_service.pluggy = FakePluggyOneAccount()

            sync_service.sync_item("item-1", session)

            acc_a = session.get(Account, "acc-a")
            acc_b = session.get(Account, "acc-b")

        self.assertTrue(acc_a.is_active)
        self.assertFalse(acc_b.is_active)
        self.assertIsNotNone(acc_b.deactivated_at)


class WebhookDeactivatesItemTest(unittest.TestCase):
    """Test 7: item/deleted webhook deactivates item and accounts."""

    def setUp(self):
        self.engine = _make_engine()

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_get_session
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_item_deleted_deactivates_item_and_accounts(self):
        with Session(self.engine) as session:
            _seed_item(session, "item-x", is_active=True)
            _seed_account(session, "acc-x1", "item-x", "BANK", is_active=True)
            _seed_account(session, "acc-x2", "item-x", "CREDIT", is_active=True)

        resp = self.client.post(
            "/webhooks/pluggy",
            json={"event": "item/deleted", "itemId": "item-x"},
        )
        self.assertEqual(resp.status_code, 202)
        data = resp.json()
        self.assertEqual(data["action"], "item_deactivated")

        with Session(self.engine) as session:
            item = session.get(Item, "item-x")
            acc1 = session.get(Account, "acc-x1")
            acc2 = session.get(Account, "acc-x2")

        self.assertFalse(item.is_active)
        self.assertIsNotNone(item.deactivated_at)
        self.assertFalse(acc1.is_active)
        self.assertFalse(acc2.is_active)

    def test_item_deleted_unknown_returns_item_not_found(self):
        resp = self.client.post(
            "/webhooks/pluggy",
            json={"event": "item/deleted", "itemId": "nonexistent"},
        )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()["action"], "item_not_found")

    def test_item_removed_and_disconnected_also_deactivate(self):
        for event in ("item/removed", "item/disconnected"):
            with self.subTest(event=event):
                item_id = f"item-{event.replace('/', '-')}"
                with Session(self.engine) as session:
                    _seed_item(session, item_id, is_active=True)

                resp = self.client.post(
                    "/webhooks/pluggy",
                    json={"event": event, "itemId": item_id},
                )
                self.assertEqual(resp.status_code, 202)
                self.assertEqual(resp.json()["action"], "item_deactivated")


class SyncHealthIncludesLifecycleFieldsTest(unittest.TestCase):
    """Test 8: /sync/health includes is_active and deactivated_at."""

    def setUp(self):
        self.engine = _make_engine()

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_get_session
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_health_includes_lifecycle_fields(self):
        with Session(self.engine) as session:
            _seed_item(session, "item-health", is_active=True)

        resp = self.client.get("/sync/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        entry = data[0]
        self.assertIn("is_active", entry)
        self.assertIn("deactivated_at", entry)
        self.assertTrue(entry["is_active"])
        self.assertIsNone(entry["deactivated_at"])

    def test_health_shows_inactive_item(self):
        with Session(self.engine) as session:
            item = _seed_item(session, "item-dead", is_active=False)
            item.deactivated_at = datetime(2026, 5, 1, 12, 0, 0)
            session.add(item)
            session.commit()

        resp = self.client.get("/sync/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        entry = next(e for e in data if e["item_id"] == "item-dead")
        self.assertFalse(entry["is_active"])
        self.assertIsNotNone(entry["deactivated_at"])


class BankCashflowMonthlyExcludesInactiveTest(unittest.TestCase):
    """Bank cashflow monthly endpoint excludes inactive Items/Accounts."""

    def setUp(self):
        self.engine = _make_engine()

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_get_session
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_inactive_account_excluded_from_monthly_cashflow(self):
        today = date.today()
        with Session(self.engine) as session:
            _seed_item(session, "item-itau", is_active=True)
            _seed_item(session, "item-caixa", is_active=False)
            _seed_account(session, "bank-itau", "item-itau", "BANK",
                          is_active=True)
            _seed_account(session, "bank-caixa", "item-caixa", "BANK",
                          is_active=False)
            session.add(Transaction(
                id="tx-itau-in",
                account_id="bank-itau",
                date=today,
                amount=Decimal("1000"),
                description="Salario Itau",
                category="Salary",
            ))
            session.add(Transaction(
                id="tx-itau-out",
                account_id="bank-itau",
                date=today,
                amount=Decimal("-100"),
                description="Pix enviado",
                category="Transfers",
            ))
            session.add(Transaction(
                id="tx-caixa-in",
                account_id="bank-caixa",
                date=today,
                amount=Decimal("3000"),
                description="Salario Caixa",
                category="Salary",
            ))
            session.add(Transaction(
                id="tx-caixa-out",
                account_id="bank-caixa",
                date=today,
                amount=Decimal("-500"),
                description="Pix Caixa",
                category="Transfers",
            ))
            session.commit()

        resp = self.client.get("/bank-cashflow/monthly", params={"months": 1})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()

        self.assertEqual(payload["bank_account_count"], 1)

        month = payload["months"][0]
        self.assertAlmostEqual(month["income"], 1000.0)
        self.assertAlmostEqual(month["outflow"], 100.0)

        tx_ids = {tx["id"] for tx in month["transactions"]}
        self.assertIn("tx-itau-in", tx_ids)
        self.assertIn("tx-itau-out", tx_ids)
        self.assertNotIn("tx-caixa-in", tx_ids)
        self.assertNotIn("tx-caixa-out", tx_ids)


if __name__ == "__main__":
    unittest.main()
