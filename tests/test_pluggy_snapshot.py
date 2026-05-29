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
        # Map bill_id → list of raw transaction dicts for bill-scoped fetches.
        self.bill_transactions: dict = {}
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

    def list_transactions(self, account_id: str, from_date=None, bill_id=None):
        # Bill-scoped transactions (keyed by bill_id)
        if bill_id is not None:
            return self.bill_transactions.get(bill_id, [])
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
    def test_spending_capacity_current_month_uses_pending_not_bill(self):
        """For the current month, spending_capacity uses PENDING-based open invoice,
        NOT CreditCardBill.  The bill exists but must be ignored for the live invoice.
        """
        from app.services.fixed_costs import spending_capacity_summary

        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)

            capacity = spending_capacity_summary(
                session, "2026-05", today=self.today
            )
            # CreditCardBill exists (from FakePluggy) but must NOT be the source
            self.assertNotEqual(capacity["card_invoice_source"], "bill")
            # No PENDING transactions → falls back to account_balance_fallback
            self.assertEqual(capacity["card_invoice_source"], "account_balance_fallback")
            # official_total = Account.balance (1500) via fallback
            self.assertEqual(capacity["card_invoice_official_total"], 1500.0)
            # Transaction-reconstructed invoice still exposed as audit value
            self.assertIn("card_invoice_gross_total", capacity)
            # New open-invoice fields are present
            self.assertIn("card_invoice_current_open_total", capacity)
            self.assertIn("card_invoice_current_open_source", capacity)

    def test_falls_back_to_account_balance_without_bill(self):
        """Without a CreditCardBill and without PENDING transactions, the current-month
        open invoice falls back to Account.balance (source = "account_balance_fallback").
        """
        from app.services.fixed_costs import spending_capacity_summary

        self.fake_pluggy.bills_supported = False
        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)

            # No bills, no PENDING → falls back to Account.balance
            capacity = spending_capacity_summary(
                session, "2026-05", today=self.today
            )
            self.assertEqual(capacity["card_invoice_source"], "account_balance_fallback")
            self.assertEqual(capacity["card_invoice_official_total"], 1500.0)


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


class CreditCardObligationSummaryTest(_SyncTestBase):
    """Tests for the 3-tier source hierarchy in credit_card_obligation_summary."""

    def test_source_bill_when_bill_exists(self):
        from app.services.pluggy_snapshot import credit_card_obligation_summary

        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)

            summary = credit_card_obligation_summary(session, "2026-05")
            self.assertEqual(summary["source"], "bill")
            self.assertEqual(summary["official_bill_total"], 1500.0)
            self.assertIn("2026-05-17", summary["due_dates"])
            self.assertEqual(len(summary["cards"]), 1)
            self.assertEqual(summary["cards"][0]["account_id"], "credit-1")

    def test_source_account_balance_when_no_bill(self):
        from app.services.pluggy_snapshot import credit_card_obligation_summary

        self.fake_pluggy.bills_supported = False
        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)

            summary = credit_card_obligation_summary(session, "2026-05")
            self.assertEqual(summary["source"], "account_balance")
            self.assertEqual(summary["current_open_total"], 1500.0)
            self.assertIsNone(summary["official_bill_total"])

    def test_source_transaction_fallback_when_no_bill_no_balance(self):
        from app.services.pluggy_snapshot import credit_card_obligation_summary

        with Session(self.engine) as session:
            session.add(
                Item(id="item-1", connector_id=200, connector_name="Test", status="UPDATED")
            )
            session.add(
                Account(id="credit-no-balance", item_id="item-1", name="No Balance Card", type="CREDIT")
            )
            session.commit()

            summary = credit_card_obligation_summary(session, "2026-05")
            self.assertEqual(summary["source"], "transaction_fallback")
            self.assertIsNone(summary["official_bill_total"])
            self.assertEqual(summary["due_dates"], [])

    def test_spending_capacity_has_card_context_fields(self):
        from app.services.fixed_costs import spending_capacity_summary

        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)

            capacity = spending_capacity_summary(session, "2026-05", today=self.today)
            self.assertIn("card_open_balance_total", capacity)
            self.assertIn("credit_card_due_dates", capacity)
            # Current month: PENDING-based estimate — CreditCardBill NOT used as source
            self.assertNotEqual(capacity["card_invoice_source"], "bill")
            self.assertEqual(capacity["card_invoice_source"], "account_balance_fallback")
            # card_open_balance_total still reflects Account.balance snapshot
            self.assertEqual(capacity["card_open_balance_total"], 1500.0)
            # New open-invoice fields are present
            self.assertIn("card_invoice_current_open_total", capacity)
            self.assertIn("card_invoice_current_open_source", capacity)
            self.assertIn("card_invoice_current_open_label", capacity)
            self.assertIn("card_invoice_cycle_start", capacity)
            self.assertIn("card_invoice_cycle_end", capacity)
            self.assertIn("card_invoice_transaction_count", capacity)

    def test_budget_available_unchanged_by_bill_context(self):
        """Adding bill context must not double-count against budget_available_to_spend."""
        from app.services.fixed_costs import spending_capacity_summary

        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)

            capacity_with_bill = spending_capacity_summary(
                session, "2026-05", today=self.today
            )
            # source is "bill" but budget_available_to_spend must not be reduced
            # by the bill total (purchases already consumed their category budgets)
            self.assertIn("budget_available_to_spend", capacity_with_bill)
            self.assertNotEqual(
                capacity_with_bill["budget_available_to_spend"],
                capacity_with_bill["budget_available_to_spend"] - capacity_with_bill["card_invoice_official_total"],
            )

    # ----- account_balance tier is current-month-only -----

    def test_future_month_without_bill_uses_transaction_fallback(self):
        """For a future month with no CreditCardBill, Account.balance must NOT
        be used — it represents today's open invoice, not a future obligation.
        The source should be transaction_fallback."""
        from app.services.pluggy_snapshot import credit_card_obligation_summary

        self.fake_pluggy.bills_supported = False
        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)
            # Confirm the account got a balance from sync
            acc = session.get(Account, "credit-1")
            self.assertIsNotNone(acc.balance)

            # Ask for the NEXT month (future relative to today=2026-05-28)
            summary = credit_card_obligation_summary(session, "2026-06", today=self.today)

        self.assertEqual(summary["source"], "transaction_fallback")
        self.assertIsNone(summary["official_bill_total"])
        # No future transactions exist → reconstruction total is zero
        self.assertEqual(summary["current_open_total"], 0.0)

    def test_past_month_without_bill_uses_transaction_fallback(self):
        """For a past month with no CreditCardBill, Account.balance must NOT
        be used — it represents today's snapshot, not the past obligation."""
        from app.services.pluggy_snapshot import credit_card_obligation_summary

        self.fake_pluggy.bills_supported = False
        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)

            # Ask for a PAST month (before today=2026-05-28)
            summary = credit_card_obligation_summary(session, "2026-04", today=self.today)

        self.assertEqual(summary["source"], "transaction_fallback")
        self.assertIsNone(summary["official_bill_total"])

    def test_future_month_with_bill_uses_bill(self):
        """A CreditCardBill with due_date in a future month must be used
        regardless — Tier 1 (official bill) always wins."""
        from app.services.pluggy_snapshot import credit_card_obligation_summary

        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)
            # Add an official bill due in next month
            session.add(CreditCardBill(
                id="bill-future-1",
                account_id="credit-1",
                due_date=date(2026, 6, 10),
                total_amount=Decimal("2500"),
            ))
            session.commit()

            summary = credit_card_obligation_summary(session, "2026-06", today=self.today)

        self.assertEqual(summary["source"], "bill")
        self.assertEqual(summary["official_bill_total"], 2500.0)
        self.assertIn("2026-06-10", summary["due_dates"])

    def test_spending_capacity_future_month_not_contaminated_by_account_balance(self):
        """spending_capacity_summary for a future month must not carry the
        current Account.balance into card_invoice_official_total / remaining."""
        from app.services.fixed_costs import spending_capacity_summary

        self.fake_pluggy.bills_supported = False
        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)
            acc = session.get(Account, "credit-1")
            balance = float(acc.balance)

            capacity = spending_capacity_summary(session, "2026-06", today=self.today)

        # Source must be transaction_fallback, not account_balance
        self.assertEqual(capacity["card_invoice_source"], "transaction_fallback")
        # The official total must NOT equal Account.balance
        self.assertNotEqual(capacity["card_invoice_official_total"], balance)
        # No future card transactions exist → gross = 0, official = 0, gap = 0
        self.assertEqual(capacity["card_invoice_gross_total"], 0.0)
        self.assertEqual(capacity["card_invoice_official_total"], 0.0)
        self.assertEqual(capacity["card_invoice_remaining_to_reserve"], 0.0)


class TransactionBillInstallmentTest(unittest.TestCase):
    """Tests that bill/installment fields are persisted through upsert_transaction."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            session.add(
                Item(id="item-1", connector_id=1, connector_name="Test", status="UPDATED")
            )
            session.add(
                Account(id="credit-1", item_id="item-1", name="Card", type="CREDIT")
            )
            session.commit()

    def test_upsert_transaction_persists_bill_installment_fields(self):
        from decimal import Decimal
        from app.services.sync import upsert_transaction

        raw = {
            "id": "tx-installment",
            "date": "2026-05-15",
            "amount": -300.0,
            "description": "Notebook 3/12",
            "category": "Electronics",
            "currencyCode": "BRL",
            "status": "POSTED",
            "billId": "bill-1",
            "installmentNumber": 3,
            "totalInstallments": 12,
            "totalAmount": -3600.0,
        }
        with Session(self.engine) as session:
            is_new, _, _ = upsert_transaction(raw, "credit-1", session)
            session.commit()

            tx = session.get(Transaction, "tx-installment")
            self.assertTrue(is_new)
            self.assertEqual(tx.status, "POSTED")
            self.assertEqual(tx.bill_id, "bill-1")
            self.assertEqual(tx.installment_number, 3)
            self.assertEqual(tx.total_installments, 12)
            self.assertEqual(tx.total_amount, Decimal("-3600.0000000000"))

    def test_upsert_transaction_null_fields_when_absent(self):
        from app.services.sync import upsert_transaction

        raw = {
            "id": "tx-plain",
            "date": "2026-05-20",
            "amount": -50.0,
            "description": "Coffee",
            "currencyCode": "BRL",
        }
        with Session(self.engine) as session:
            upsert_transaction(raw, "credit-1", session)
            session.commit()

            tx = session.get(Transaction, "tx-plain")
            self.assertIsNone(tx.status)
            self.assertIsNone(tx.bill_id)
            self.assertIsNone(tx.installment_number)
            self.assertIsNone(tx.total_amount)


class BillTransactionSyncTest(_SyncTestBase):
    """Bill-scoped transaction sync: after bill rows are committed,
    transactions are fetched per bill_id and persisted with bill metadata."""

    def test_bill_transactions_are_fetched_and_persisted(self):
        """Transactions returned for a bill_id are upserted and carry
        the bill_id field so they can be correlated to their bill."""
        # FakePluggy.list_bills returns a bill with id "bill-1" for credit-1.
        self.fake_pluggy.bill_transactions["bill-1"] = [
            {
                "id": "tx-bill-1",
                "date": "2026-05-10",
                "amount": -250.0,
                "description": "Supermercado",
                "category": "Supermarket",
                "currencyCode": "BRL",
                "status": "POSTED",
                "billId": "bill-1",
            },
            {
                # Installment purchase — carries full installment metadata
                "id": "tx-bill-2",
                "date": "2026-05-15",
                "amount": -300.0,
                "description": "Notebook 3/12",
                "category": "Electronics",
                "currencyCode": "BRL",
                "status": "POSTED",
                "billId": "bill-1",
                "installmentNumber": 3,
                "totalInstallments": 12,
                "totalAmount": -3600.0,
            },
        ]

        with Session(self.engine) as session:
            self._seed_item(session)
            result = sync_service.sync_item("item-1", session)

        # Counters must reflect the two bill transactions
        self.assertEqual(result["bills_upserted"], 1)  # bill-1
        self.assertEqual(result["bill_transactions_fetched"], 2)
        self.assertEqual(result["bill_transactions_new"], 2)

        # Transactions are in the DB with correct bill_id and metadata
        with Session(self.engine) as session:
            tx1 = session.get(Transaction, "tx-bill-1")
            tx2 = session.get(Transaction, "tx-bill-2")
        self.assertIsNotNone(tx1)
        self.assertEqual(tx1.bill_id, "bill-1")
        self.assertEqual(tx1.status, "POSTED")
        self.assertIsNotNone(tx2)
        self.assertEqual(tx2.bill_id, "bill-1")
        self.assertEqual(tx2.installment_number, 3)
        self.assertEqual(tx2.total_installments, 12)
        self.assertEqual(tx2.total_amount, Decimal("-3600.0"))

    def test_bill_transaction_failure_does_not_break_sync(self):
        """A crash while fetching transactions for one bill must leave
        the result intact — the bill row itself was already committed."""
        # Make list_transactions raise for a specific bill_id
        original = self.fake_pluggy.list_transactions

        def flaky(account_id, from_date=None, bill_id=None):
            # "bill-1" is the id returned by FakePluggy.list_bills for credit-1
            if bill_id == "bill-1":
                raise RuntimeError("network blip")
            return original(account_id, from_date=from_date, bill_id=bill_id)

        self.fake_pluggy.list_transactions = flaky

        with Session(self.engine) as session:
            self._seed_item(session)
            result = sync_service.sync_item("item-1", session)

        # Bills still committed successfully
        self.assertGreaterEqual(result["bills_upserted"], 1)
        # The error surfaced as a note, not a crash
        bill_tx_notes = [
            n for n in result["snapshot_notes"] if n.get("scope") == "bill_transactions"
        ]
        self.assertTrue(len(bill_tx_notes) >= 1)
        self.assertIn("bill-1", bill_tx_notes[0].get("bill_id", ""))


if __name__ == "__main__":
    unittest.main()
