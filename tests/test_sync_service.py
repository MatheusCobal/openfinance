import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    Account,
    AccountSync,
    BankIncomeMonth,
    CreditCardInvoiceMonth,
    Item,
    MonthlyBalanceMonth,
    Transaction,
)
from app.services import sync as sync_service
from app.services.transactions import last_month_keys


def _snapshot(session: Session, model, year_month: str):
    return session.exec(select(model).where(model.year_month == year_month)).first()


class FakePluggy:
    def __init__(self, today: date):
        self.today = today
        self.transaction_calls = []
        self.accounts = [
            {
                "id": "credit-1",
                "name": "Credit Card",
                "type": "CREDIT",
                "subtype": "CREDIT_CARD",
                "marketingName": "Black",
                "number": "1234",
                "creditData": {"balanceDueDate": self.today.isoformat()},
            },
            {
                "id": "bank-1",
                "name": "Checking Account",
                "type": "BANK",
                "subtype": "CHECKING_ACCOUNT",
                "marketingName": "Conta",
                "number": "5678",
            },
            {
                "id": "investment-1",
                "name": "Investments",
                "type": "INVESTMENT",
            },
        ]

    def get_item(self, item_id: str):
        return {
            "id": item_id,
            "connector": {"id": 200, "name": "MeuPluggy"},
            "status": "UPDATED",
        }

    def list_accounts(self, item_id: str):
        return self.accounts

    def list_transactions(self, account_id: str, from_date=None):
        self.transaction_calls.append((account_id, from_date))
        if account_id == "credit-1":
            return [
                {
                    "id": "credit-existing",
                    "date": self.today.isoformat(),
                    "amount": -120.50,
                    "description": "Compra atualizada",
                    "category": "Shopping",
                    "currencyCode": "BRL",
                },
                {
                    "id": "credit-payment",
                    "date": self.today.isoformat(),
                    "amount": -120.50,
                    "description": "Pagamento recebido",
                    "category": "Credit card payment",
                    "currencyCode": "BRL",
                },
                {
                    "id": "credit-future",
                    "date": (self.today + timedelta(days=32)).isoformat(),
                    "amount": -40,
                    "description": "Parcela futura",
                    "category": "Shopping",
                    "currencyCode": "BRL",
                },
            ]
        if account_id == "bank-1":
            return [
                {
                    "id": "bank-income",
                    "date": self.today.isoformat(),
                    "amount": 5000,
                    "description": "Salario Empresa",
                    "category": "Salary",
                    "currencyCode": "BRL",
                },
                {
                    "id": "bank-outflow",
                    "date": self.today.isoformat(),
                    "amount": -100,
                    "description": "Pix enviado",
                    "category": "Transfers",
                    "currencyCode": "BRL",
                },
            ]
        return []


class SyncServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.today = date.today()
        self.fake_pluggy = FakePluggy(self.today)
        self.original_pluggy = sync_service.pluggy
        sync_service.pluggy = self.fake_pluggy

    def tearDown(self):
        sync_service.pluggy = self.original_pluggy

    def test_upsert_item_creates_and_updates_item_from_pluggy(self):
        with Session(self.engine) as session:
            item = sync_service.upsert_item("item-1", session)
            self.assertEqual(item.id, "item-1")
            self.assertEqual(item.connector_id, 200)
            self.assertEqual(item.connector_name, "MeuPluggy")
            self.assertEqual(item.status, "UPDATED")

            self.fake_pluggy.get_item = lambda item_id: {
                "id": item_id,
                "connector": {"id": 200, "name": "MeuPluggy Renamed"},
                "status": "LOGIN_ERROR",
            }
            item = sync_service.upsert_item("item-1", session)
            self.assertEqual(item.connector_name, "MeuPluggy Renamed")
            self.assertEqual(item.status, "LOGIN_ERROR")

            items = session.exec(select(Item)).all()
            self.assertEqual(len(items), 1)

    def test_sync_item_uses_fake_pluggy_and_updates_local_state(self):
        with Session(self.engine) as session:
            session.add(
                Item(
                    id="item-1",
                    connector_id=200,
                    connector_name="MeuPluggy",
                    status="UPDATED",
                )
            )
            session.add(
                Account(
                    id="credit-1",
                    item_id="item-1",
                    name="Old Credit",
                    type="CREDIT",
                )
            )
            session.add(
                Transaction(
                    id="credit-existing",
                    account_id="credit-1",
                    date=self.today - timedelta(days=1),
                    amount=Decimal("-100.00"),
                    description="Compra antiga",
                    category="Shopping",
                )
            )
            session.commit()

            result = sync_service.sync_item("item-1", session)

            self.assertEqual(result["tracked_accounts"], 2)
            self.assertEqual(result["credit_accounts"], 1)
            self.assertEqual(result["bank_accounts"], 1)
            self.assertEqual(result["fetched_transactions"], 5)
            self.assertEqual(result["new_transactions"], 4)
            self.assertEqual(result["updated_transactions"], 1)
            self.assertEqual(result["deleted_transactions"], 0)
            self.assertEqual(result["refreshed_income_months"], 1)
            self.assertEqual(result["refreshed_invoice_months"], 1)
            self.assertEqual(result["refreshed_balance_months"], 1)

            self.assertEqual(
                self.fake_pluggy.transaction_calls,
                [
                    ("credit-1", self.today - timedelta(days=8)),
                    ("bank-1", None),
                ],
            )

            accounts = {account.id: account for account in session.exec(select(Account)).all()}
            self.assertEqual(set(accounts.keys()), {"credit-1", "bank-1"})
            self.assertEqual(accounts["credit-1"].name, "Credit Card")
            self.assertEqual(accounts["credit-1"].marketing_name, "Black")
            self.assertEqual(accounts["bank-1"].type, "BANK")

            updated_tx = session.get(Transaction, "credit-existing")
            self.assertEqual(updated_tx.amount, Decimal("-120.5000000000"))
            self.assertEqual(updated_tx.description, "Compra atualizada")
            self.assertIsNotNone(session.get(Transaction, "credit-future"))
            self.assertIsNotNone(session.get(Transaction, "bank-income"))
            self.assertIsNone(session.get(Account, "investment-1"))

            credit_sync = session.get(AccountSync, "credit-1")
            bank_sync = session.get(AccountSync, "bank-1")
            self.assertEqual(credit_sync.last_transaction_date, self.today)
            self.assertEqual(bank_sync.last_transaction_date, self.today)
            self.assertIsNotNone(credit_sync.last_synced_at)
            self.assertIsNotNone(bank_sync.last_synced_at)

            current_month = last_month_keys(1, self.today)[0]
            income_snapshot = _snapshot(session, BankIncomeMonth, current_month)
            invoice_snapshot = _snapshot(session, CreditCardInvoiceMonth, current_month)
            balance_snapshot = _snapshot(session, MonthlyBalanceMonth, current_month)
            self.assertEqual(income_snapshot.total, Decimal("5000.0000000000"))
            self.assertEqual(income_snapshot.income_count, 1)
            self.assertEqual(invoice_snapshot.total, Decimal("120.5000000000"))
            self.assertEqual(invoice_snapshot.payment_count, 1)
            self.assertEqual(balance_snapshot.income, Decimal("5000.0000000000"))
            self.assertEqual(balance_snapshot.invoice_paid, Decimal("120.5000000000"))

    def test_itau_sync_revisits_old_pending_without_expanding_deletion_window(self):
        with Session(self.engine) as session:
            session.add(Item(id="item-1", connector_id=200, status="UPDATED"))
            session.add(
                Account(
                    id="credit-1",
                    item_id="item-1",
                    name="LATAM PASS ITAU BLACK",
                    type="CREDIT",
                )
            )
            sync_state = AccountSync(account_id="credit-1", last_transaction_date=date(2026, 8, 30))
            session.add(sync_state)
            session.add_all(
                [
                    Transaction(
                        id="old-pending-payment",
                        account_id="credit-1",
                        date=date(2026, 8, 20),
                        amount=Decimal("-5401.33"),
                        description="PAGAMENTO COM SALDO",
                        category="Transfers",
                        status="PENDING",
                        bill_forecast_month="2026-09",
                    ),
                    Transaction(
                        id="older-history",
                        account_id="credit-1",
                        date=date(2026, 7, 30),
                        amount=Decimal("105"),
                        description="Mensalidade",
                        status="PENDING",
                    ),
                    Transaction(
                        id="deleted-in-recent-window",
                        account_id="credit-1",
                        date=date(2026, 8, 29),
                        amount=Decimal("50"),
                        description="Removed by provider",
                        status="PENDING",
                    ),
                ]
            )
            session.commit()
            remote = {
                "id": "old-pending-payment",
                "date": "2026-08-20",
                "amount": -5401.33,
                "description": "PAGAMENTO COM SALDO",
                "category": "Transfers",
                "status": "POSTED",
                "creditCardMetadata": {"billForecastDate": "2026-09", "billId": "september-bill"},
            }

            def remote_transactions(account_id, from_date=None):
                return [remote] if from_date is None or from_date <= date(2026, 8, 20) else []

            with patch.object(
                self.fake_pluggy, "list_transactions", side_effect=remote_transactions
            ) as fetch:
                result = sync_service.sync_account_transactions("credit-1", sync_state, session)
                session.commit()
                fetch.assert_called_once_with("credit-1", from_date=date(2026, 7, 30))

            self.assertEqual(session.get(Transaction, "old-pending-payment").status, "POSTED")
            self.assertEqual(
                session.get(Transaction, "old-pending-payment").bill_id, "september-bill"
            )
            self.assertEqual(session.get(Transaction, "older-history").status, "PENDING")
            self.assertEqual(result.deleted_transactions, 1)
            self.assertIsNone(session.get(Transaction, "deleted-in-recent-window"))
            self.assertEqual(sync_state.last_transaction_date, date(2026, 8, 30))

    def test_caixa_sync_keeps_existing_lookback_with_old_pending(self):
        with Session(self.engine) as session:
            session.add(Item(id="item-1", connector_id=200, status="UPDATED"))
            session.add(
                Account(
                    id="credit-1",
                    item_id="item-1",
                    name="CAIXA ICONE VISA",
                    type="CREDIT",
                )
            )
            sync_state = AccountSync(account_id="credit-1", last_transaction_date=date(2026, 8, 30))
            session.add(sync_state)
            session.add(
                Transaction(
                    id="old-caixa-payment",
                    account_id="credit-1",
                    date=date(2026, 8, 20),
                    amount=Decimal("-8418.39"),
                    description="Pagamento",
                    status="PENDING",
                )
            )
            session.commit()
            with patch.object(self.fake_pluggy, "list_transactions", return_value=[]) as fetch:
                sync_service.sync_account_transactions("credit-1", sync_state, session)
                session.commit()
                fetch.assert_called_once_with("credit-1", from_date=date(2026, 8, 23))
            self.assertEqual(session.get(Transaction, "old-caixa-payment").status, "PENDING")

    def test_sync_deletes_transactions_missing_from_authoritative_window(self):
        with Session(self.engine) as session:
            session.add(Item(id="item-1", connector_id=200, status="UPDATED"))
            session.add(
                Account(
                    id="credit-1",
                    item_id="item-1",
                    name="Credit Card",
                    type="CREDIT",
                )
            )
            session.add(
                AccountSync(
                    account_id="credit-1",
                    last_transaction_date=self.today,
                )
            )
            session.add(
                Transaction(
                    id="deleted-by-pluggy",
                    account_id="credit-1",
                    date=self.today,
                    amount=Decimal("10"),
                    description="Deleted remotely",
                )
            )
            session.add(
                Transaction(
                    id="old-local-history",
                    account_id="credit-1",
                    date=self.today - timedelta(days=30),
                    amount=Decimal("20"),
                    description="Outside reconciliation window",
                )
            )
            session.commit()

            result = sync_service.sync_item("item-1", session)

            self.assertEqual(result["deleted_transactions"], 1)
            self.assertIsNone(session.get(Transaction, "deleted-by-pluggy"))
            self.assertIsNotNone(session.get(Transaction, "old-local-history"))


class SyncIsolationAndLockTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.today = date.today()
        self.fake_pluggy = FakePluggy(self.today)
        self.original_pluggy = sync_service.pluggy
        sync_service.pluggy = self.fake_pluggy

    def tearDown(self):
        sync_service.pluggy = self.original_pluggy

    def _seed_item(self, session):
        session.add(
            Item(
                id="item-1",
                connector_id=200,
                connector_name="MeuPluggy",
                status="UPDATED",
            )
        )
        session.commit()

    def test_account_failure_preserves_other_accounts(self):
        # bank-1 raises mid-loop; credit-1 must still be persisted, and
        # AccountSync["bank-1"] must record the error.
        original_list = self.fake_pluggy.list_transactions

        def flaky_list(account_id, from_date=None):
            if account_id == "bank-1":
                raise RuntimeError("pluggy 500")
            return original_list(account_id, from_date)

        self.fake_pluggy.list_transactions = flaky_list

        with Session(self.engine) as session:
            self._seed_item(session)
            result = sync_service.sync_item("item-1", session)

            self.assertEqual(len(result["failed_accounts"]), 1)
            self.assertEqual(result["failed_accounts"][0]["account_id"], "bank-1")
            self.assertIn("pluggy 500", result["failed_accounts"][0]["error"])

            # credit-1 transactions still made it through
            self.assertIsNotNone(session.get(Transaction, "credit-payment"))

            bank_sync = session.get(AccountSync, "bank-1")
            self.assertIsNotNone(bank_sync)
            self.assertIn("pluggy 500", bank_sync.last_error)
            self.assertIsNotNone(bank_sync.last_error_at)
            failed_account = session.get(Account, "bank-1")
            self.assertIsNotNone(failed_account)
            self.assertEqual(failed_account.item_id, "item-1")

            credit_sync = session.get(AccountSync, "credit-1")
            self.assertIsNone(credit_sync.last_error)

            item = session.get(Item, "item-1")
            self.assertIsNotNone(item.sync_finished_at)
            self.assertIsNone(item.last_sync_error)  # top-level didn't fail
            self.assertFalse(sync_service.is_sync_running(item))

    def test_concurrent_sync_raises_already_running(self):
        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service._acquire_sync_lock("item-1", session)

            with self.assertRaises(sync_service.SyncAlreadyRunning):
                sync_service.sync_item("item-1", session)
            self.assertEqual(self.fake_pluggy.transaction_calls, [])

    def test_stale_lock_is_recoverable(self):
        with Session(self.engine) as session:
            self._seed_item(session)
            stale = datetime.utcnow() - timedelta(minutes=30)
            item = session.get(Item, "item-1")
            item.sync_started_at = stale
            item.sync_finished_at = None
            session.add(item)
            session.commit()

            # Should acquire despite no sync_finished_at, because lock is stale.
            result = sync_service.sync_item("item-1", session)
            self.assertEqual(result["failed_accounts"], [])

            item = session.get(Item, "item-1")
            self.assertIsNotNone(item.sync_finished_at)
            self.assertIsNone(item.last_sync_error)
            self.assertFalse(sync_service.is_sync_running(item))

    def test_top_level_failure_releases_lock(self):
        def boom(item_id):
            raise RuntimeError("list_accounts down")

        self.fake_pluggy.list_accounts = boom

        with Session(self.engine) as session:
            self._seed_item(session)
            with self.assertRaises(RuntimeError):
                sync_service.sync_item("item-1", session)

            item = session.get(Item, "item-1")
            self.assertIsNotNone(item.sync_finished_at)
            self.assertIn("list_accounts down", item.last_sync_error)
            self.assertFalse(sync_service.is_sync_running(item))


if __name__ == "__main__":
    unittest.main()
