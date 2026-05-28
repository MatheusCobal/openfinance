import unittest
from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    Account,
    CreditCardBill,
    Investment,
    InvestmentTransaction,
    Item,
    Transaction,
)
from app.services import sync as sync_service
from app.services.pluggy_snapshot import account_snapshot_summary
from app.services.reserve import emergency_reserve_monthly_summary


def _http_404(path: str) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", f"https://api.pluggy.ai{path}")
    response = httpx.Response(404, request=request)
    return httpx.HTTPStatusError("not found", request=request, response=response)


class FakePluggy:
    """Fake Pluggy that implements the full snapshot surface.

    Flags let individual tests turn endpoints into 404s to exercise the
    graceful-degradation path.
    """

    def __init__(self, today: date):
        self.today = today
        self.bills_supported = True
        self.investments_supported = True
        self.accounts = [
            {
                "id": "credit-1",
                "name": "Credit Card",
                "type": "CREDIT",
                "subtype": "CREDIT_CARD",
                "marketingName": "Black",
                "number": "1234",
                "balance": 1500.00,
                "currencyCode": "BRL",
                "owner": "Matheus",
                "taxNumber": "***",
                "creditData": {
                    "level": "BLACK",
                    "brand": "VISA",
                    "balanceCloseDate": "2026-05-10",
                    "balanceDueDate": "2026-05-17",
                    "availableCreditLimit": 8500.0,
                    "creditLimit": 10000.0,
                    "minimumPayment": 150.0,
                    "status": "OPEN",
                    "holderType": "MAIN",
                },
                "updatedAt": "2026-05-27T12:00:00Z",
            },
            {
                "id": "bank-1",
                "name": "Checking Account",
                "type": "BANK",
                "subtype": "CHECKING_ACCOUNT",
                "marketingName": "Conta",
                "number": "5678",
                "balance": 5000.0,
                "currencyCode": "BRL",
                "bankData": {
                    "closingBalance": 5000.0,
                    "automaticallyInvestedBalance": 200.0,
                    "overdraftContractedLimit": 1000.0,
                    "overdraftUsedLimit": 0.0,
                },
                "updatedAt": "2026-05-27T12:00:00Z",
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
        if account_id == "credit-1":
            return [
                {
                    "id": "credit-buy",
                    "date": self.today.isoformat(),
                    "amount": -1500.0,
                    "description": "Compra cartao",
                    "category": "Shopping",
                    "currencyCode": "BRL",
                },
            ]
        if account_id == "bank-1":
            return [
                {
                    "id": "bank-income",
                    "date": self.today.isoformat(),
                    "amount": 5000.0,
                    "description": "Salario",
                    "category": "Salary",
                    "currencyCode": "BRL",
                },
            ]
        return []

    def list_bills(self, account_id: str):
        if not self.bills_supported:
            raise _http_404("/bills")
        if account_id == "credit-1":
            return [
                {
                    "id": "bill-1",
                    "dueDate": "2026-05-17",
                    "totalAmount": 1500.0,
                    "minimumPaymentAmount": 150.0,
                    "allowsInstallments": True,
                    "payments": {"totalAmount": 0},
                    "financeCharges": {"totalAmount": 0},
                    "currencyCode": "BRL",
                }
            ]
        return []

    def list_investments(self, item_id: str):
        if not self.investments_supported:
            raise _http_404("/investments")
        return [
            {
                "id": "inv-cdb",
                "name": "CDB Banco X",
                "type": "FIXED_INCOME",
                "subtype": "CDB",
                "amount": 10000.0,
                "balance": 10500.0,
                "amountOriginal": 10000.0,
                "amountProfit": 500.0,
                "amountWithdrawal": 0.0,
                "rate": 1.1,
                "rateType": "CDI",
                "fixedAnnualRate": None,
                "issuer": "Banco X",
                "issueDate": "2025-01-01",
                "dueDate": "2027-01-01",
                "status": "ACTIVE",
                "currencyCode": "BRL",
                "providerId": "prov-1",
            },
            {
                "id": "inv-stock",
                "name": "Ações XPTO",
                "type": "EQUITY",
                "subtype": "STOCK",
                "amount": 3000.0,
                "balance": 3200.0,
                "status": "ACTIVE",
                "currencyCode": "BRL",
            },
        ]

    def list_investment_transactions(self, investment_id: str, from_date=None):
        if not self.investments_supported:
            raise _http_404("/investments/transactions")
        if investment_id == "inv-cdb":
            return [
                {
                    "id": "itx-buy",
                    "date": "2026-05-05",
                    "tradeDate": "2026-05-05",
                    "type": "BUY",
                    "description": "Aplicacao CDB",
                    "amount": 1000.0,
                    "netAmount": 1000.0,
                    "quantity": 1,
                    "value": 1000.0,
                    "currencyCode": "BRL",
                },
                {
                    "id": "itx-sell",
                    "date": "2026-05-20",
                    "tradeDate": "2026-05-20",
                    "type": "SELL",
                    "description": "Resgate CDB",
                    "amount": 300.0,
                    "netAmount": 300.0,
                    "quantity": 1,
                    "value": 300.0,
                    "currencyCode": "BRL",
                },
                {
                    "id": "itx-tax",
                    "date": "2026-05-20",
                    "tradeDate": "2026-05-20",
                    "type": "TAX",
                    "description": "IR",
                    "amount": 30.0,
                    "netAmount": 30.0,
                    "currencyCode": "BRL",
                },
            ]
        return []


class _SyncTestBase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.today = date(2026, 5, 28)
        self.fake_pluggy = FakePluggy(self.today)
        self.original_pluggy = sync_service.pluggy
        sync_service.pluggy = self.fake_pluggy
        # pluggy_snapshot.py imports `pluggy` directly, so patch it there too.
        import app.services.pluggy_snapshot as snap

        self.snap_module = snap
        self.original_snap_pluggy = snap.pluggy
        snap.pluggy = self.fake_pluggy

    def tearDown(self):
        sync_service.pluggy = self.original_pluggy
        self.snap_module.pluggy = self.original_snap_pluggy

    def _seed_item(self, session):
        session.add(
            Item(id="item-1", connector_id=200, connector_name="MeuPluggy", status="UPDATED")
        )
        session.commit()


class AccountSnapshotSyncTest(_SyncTestBase):
    def test_sync_persists_balance_bankdata_creditdata(self):
        with Session(self.engine) as session:
            self._seed_item(session)
            result = sync_service.sync_item("item-1", session)

            self.assertEqual(result["bills_upserted"], 1)
            self.assertEqual(result["investments_upserted"], 2)
            self.assertEqual(result["investment_transactions_upserted"], 3)
            self.assertEqual(result["snapshot_notes"], [])

            credit = session.get(Account, "credit-1")
            self.assertEqual(credit.balance, Decimal("1500.0000000000"))
            self.assertEqual(credit.currency_code, "BRL")
            self.assertEqual(credit.owner, "Matheus")
            self.assertEqual(credit.credit_brand, "VISA")
            self.assertEqual(credit.credit_level, "BLACK")
            self.assertEqual(credit.credit_limit, Decimal("10000.0000000000"))
            self.assertEqual(credit.credit_available_limit, Decimal("8500.0000000000"))
            self.assertEqual(credit.credit_minimum_payment, Decimal("150.0000000000"))
            self.assertEqual(credit.credit_balance_close_date, date(2026, 5, 10))
            self.assertEqual(credit.credit_balance_due_date, date(2026, 5, 17))
            self.assertIsNotNone(credit.balance_updated_at)

            bank = session.get(Account, "bank-1")
            self.assertEqual(bank.balance, Decimal("5000.0000000000"))
            self.assertEqual(bank.bank_closing_balance, Decimal("5000.0000000000"))
            self.assertEqual(
                bank.bank_automatically_invested_balance, Decimal("200.0000000000")
            )
            self.assertEqual(
                bank.bank_overdraft_contracted_limit, Decimal("1000.0000000000")
            )

    def test_bills_and_investments_persisted(self):
        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)

            bill = session.get(CreditCardBill, "bill-1")
            self.assertIsNotNone(bill)
            self.assertEqual(bill.account_id, "credit-1")
            self.assertEqual(bill.total_amount, Decimal("1500.0000000000"))
            self.assertEqual(bill.minimum_payment_amount, Decimal("150.0000000000"))
            self.assertEqual(bill.due_date, date(2026, 5, 17))

            inv = session.get(Investment, "inv-cdb")
            self.assertIsNotNone(inv)
            self.assertEqual(inv.type, "FIXED_INCOME")
            self.assertEqual(inv.balance, Decimal("10500.0000000000"))
            self.assertEqual(inv.amount_profit, Decimal("500.0000000000"))

            buy = session.get(InvestmentTransaction, "itx-buy")
            self.assertEqual(buy.type, "BUY")
            self.assertEqual(buy.amount, Decimal("1000.0000000000"))
            self.assertEqual(buy.investment_id, "inv-cdb")


class DashboardSnapshotTest(_SyncTestBase):
    def test_dashboard_totals_from_pluggy_snapshot(self):
        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)

            summary = account_snapshot_summary(session)

            # Bank total from Account.balance, not transactions
            self.assertEqual(summary["bank"]["total"], 5000.0)
            self.assertTrue(summary["bank"]["has_balance"])

            # Credit usage + limits from Account.balance / creditData
            self.assertEqual(summary["credit"]["used"], 1500.0)
            self.assertEqual(summary["credit"]["limit"], 10000.0)
            self.assertEqual(summary["credit"]["available"], 8500.0)

            # Investments total = sum(Investment.balance) (CDB + stock)
            self.assertEqual(summary["investments"]["total"], 13700.0)
            # Reserve total = only reserve-eligible (FIXED_INCOME CDB)
            self.assertEqual(summary["investments"]["reserve_total"], 10500.0)
            self.assertEqual(summary["investments"]["reserve_investment_count"], 1)


class CreditCardBillVsReconstructedTest(_SyncTestBase):
    def test_spending_capacity_prefers_official_bill(self):
        from app.services.fixed_costs import spending_capacity_summary

        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)

            capacity = spending_capacity_summary(
                session, "2026-05", today=self.today
            )
            # Bill due 2026-05-17 totalling 1500 → official source
            self.assertEqual(capacity["card_invoice_source"], "bill")
            self.assertEqual(capacity["card_invoice_official_total"], 1500.0)
            # Transaction-reconstructed invoice still exposed as audit value
            self.assertIn("card_invoice_gross_total", capacity)

    def test_falls_back_to_reconstructed_invoice_without_bill(self):
        from app.services.fixed_costs import spending_capacity_summary

        self.fake_pluggy.bills_supported = False
        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)

            capacity = spending_capacity_summary(
                session, "2026-05", today=self.today
            )
            self.assertEqual(capacity["card_invoice_source"], "transactions")


class ReserveSourceTest(_SyncTestBase):
    def test_reserve_uses_investment_snapshot_when_available(self):
        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)

            summary = emergency_reserve_monthly_summary(
                session, months=6, today=self.today
            )
            self.assertEqual(summary["source"], "pluggy")
            # Current reserve balance straight from Investment.balance (CDB)
            self.assertEqual(summary["current_reserve_balance"], 10500.0)

            may = next(m for m in summary["months"] if m["year_month"] == "2026-05")
            # BUY 1000, SELL 300, TAX 30
            self.assertEqual(may["applications_total"], 1000.0)
            self.assertEqual(may["rescues_total"], 300.0)
            self.assertEqual(may["taxes_total"], 30.0)
            self.assertEqual(may["net_total"], 700.0)
            self.assertEqual(may["application_count"], 1)
            self.assertEqual(may["rescue_count"], 1)
            self.assertEqual(may["tax_count"], 1)

    def test_reserve_falls_back_to_transactions_without_investments(self):
        with Session(self.engine) as session:
            self._seed_item(session)
            # Bank account + a "Fixed income" CDB application transaction,
            # but NO investments persisted.
            session.add(
                Account(id="bank-1", item_id="item-1", name="Bank", type="BANK")
            )
            session.add(
                Transaction(
                    id="tx-cdb",
                    account_id="bank-1",
                    date=date(2026, 5, 6),
                    amount=Decimal("-2000"),
                    description="Aplicacao CDB",
                    category="Fixed income",
                )
            )
            session.commit()

            summary = emergency_reserve_monthly_summary(
                session, months=6, today=self.today
            )
            self.assertEqual(summary["source"], "transactions")
            may = next(m for m in summary["months"] if m["year_month"] == "2026-05")
            self.assertEqual(may["applications_total"], 2000.0)


class GracefulDegradationTest(_SyncTestBase):
    def test_sync_continues_when_bills_and_investments_unavailable(self):
        self.fake_pluggy.bills_supported = False
        self.fake_pluggy.investments_supported = False

        with Session(self.engine) as session:
            self._seed_item(session)
            result = sync_service.sync_item("item-1", session)

            # Core transaction sync untouched
            self.assertEqual(result["failed_accounts"], [])
            self.assertIsNotNone(session.get(Transaction, "credit-buy"))
            self.assertIsNotNone(session.get(Transaction, "bank-income"))

            # Snapshots simply skipped, recorded as notes (not failures)
            self.assertEqual(result["bills_upserted"], 0)
            self.assertEqual(result["investments_upserted"], 0)
            scopes = {note["scope"] for note in result["snapshot_notes"]}
            self.assertIn("bills", scopes)
            self.assertIn("investments", scopes)
            for note in result["snapshot_notes"]:
                self.assertIsNotNone(note.get("skipped"))
                self.assertIsNone(note.get("error"))

            # Account balances still persisted (they come from list_accounts)
            self.assertEqual(session.get(Account, "bank-1").balance, Decimal("5000.0000000000"))

            # No investment rows, so reserve falls back to transactions
            summary = emergency_reserve_monthly_summary(
                session, months=6, today=self.today
            )
            self.assertEqual(summary["source"], "transactions")


if __name__ == "__main__":
    unittest.main()
