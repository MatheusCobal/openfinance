import unittest
from datetime import date, timedelta
from decimal import Decimal

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

            accounts = {
                account.id: account for account in session.exec(select(Account)).all()
            }
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
            income_snapshot = session.get(BankIncomeMonth, current_month)
            invoice_snapshot = session.get(CreditCardInvoiceMonth, current_month)
            balance_snapshot = session.get(MonthlyBalanceMonth, current_month)
            self.assertEqual(income_snapshot.total, Decimal("5000.0000000000"))
            self.assertEqual(income_snapshot.income_count, 1)
            self.assertEqual(invoice_snapshot.total, Decimal("120.5000000000"))
            self.assertEqual(invoice_snapshot.payment_count, 1)
            self.assertEqual(balance_snapshot.income, Decimal("5000.0000000000"))
            self.assertEqual(balance_snapshot.invoice_paid, Decimal("120.5000000000"))


if __name__ == "__main__":
    unittest.main()
