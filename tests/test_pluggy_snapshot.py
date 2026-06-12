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
                    "amount": 1500.0,
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
            self.assertEqual(bank.bank_automatically_invested_balance, Decimal("200.0000000000"))
            self.assertEqual(bank.bank_overdraft_contracted_limit, Decimal("1000.0000000000"))

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


class AccountSnapshotSummaryTest(_SyncTestBase):
    def test_account_snapshot_totals_from_pluggy(self):
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
            self.assertEqual(summary["investments"]["investment_count"], 2)
            self.assertNotIn("reserve_total", summary["investments"])
            self.assertNotIn("reserve_investment_count", summary["investments"])


class CreditCardBillVsReconstructedTest(_SyncTestBase):
    def test_spending_capacity_current_month_uses_transactions_not_bill(self):
        """For the current month, spending_capacity uses the transaction-based open
        invoice (bill_id=null transactions in cycle/month), NOT CreditCardBill.
        The FakePluggy syncs one credit transaction (status=null, amount=1500)
        that falls in the current month outside the billing cycle.
        """
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)

            capacity = spending_capacity_summary(session, "2026-05", today=self.today)
            # CreditCardBill exists (from FakePluggy) but must NOT be the source
            self.assertNotEqual(capacity["card_invoice_source"], "official_bill")
            # Transaction-based: 1 tx in month with bill_id=null → open_invoice
            self.assertEqual(capacity["card_invoice_source"], "open_invoice")
            # official_total = the credit transaction amount (1500)
            self.assertEqual(capacity["card_invoice_official_total"], 1500.0)
            # Transaction-reconstructed invoice still exposed as audit value
            self.assertIn("card_invoice_gross_total", capacity)
            # New open-invoice fields are present
            self.assertIn("card_invoice_current_open_total", capacity)
            self.assertIn("card_invoice_current_open_source", capacity)

    def test_falls_back_to_account_balance_without_bill(self):
        """Without a CreditCardBill the open invoice is still derived from
        the synced credit transactions (bill_id=null).  The FakePluggy credit
        transaction (amount=1500, status=null) is in the current month, so
        source = "open_invoice" with total = 1500.
        """
        from app.services.spending_capacity import spending_capacity_summary

        self.fake_pluggy.bills_supported = False
        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)

            capacity = spending_capacity_summary(session, "2026-05", today=self.today)
            self.assertEqual(capacity["card_invoice_source"], "open_invoice")
            self.assertEqual(capacity["card_invoice_official_total"], 1500.0)


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

            self.assertEqual(session.exec(select(Investment)).all(), [])


class PlanningInvoiceForMonthTest(_SyncTestBase):
    """planning_invoice_for_month — the single source of truth for the planning
    invoice. ``today`` is always passed explicitly so tests are deterministic
    regardless of the system clock."""

    REQUIRED_KEYS = (
        "year_month",
        "amount",
        "source",
        "source_label",
        "is_estimated",
        "due_dates",
        "cards",
        "transaction_count",
        "bill_count",
        "account_count",
        "cycle_start",
        "cycle_end",
    )

    def _seed_credit(self, session, **kwargs):
        session.add(Item(id="item-1", connector_id=200, connector_name="T", status="UPDATED"))
        defaults = dict(id="cc1", item_id="item-1", name="CC", type="CREDIT")
        defaults.update(kwargs)
        session.add(Account(**defaults))
        session.commit()

    # ----- result shape -----

    def test_result_has_required_keys(self):
        from app.services.credit_card_invoice import planning_invoice_for_month

        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)
            inv = planning_invoice_for_month(session, "2026-05", today=self.today)
        for key in self.REQUIRED_KEYS:
            self.assertIn(key, inv, f"missing key: {key}")

    # ----- current month -----

    def test_current_month_open_invoice(self):
        """Current month uses the open invoice estimated from bill_id-null card
        transactions (NOT the official CreditCardBill)."""
        from app.services.credit_card_invoice import planning_invoice_for_month

        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)
            inv = planning_invoice_for_month(session, "2026-05", today=self.today)
        self.assertEqual(inv["source"], "open_invoice")
        self.assertEqual(inv["amount"], 1500.0)
        self.assertEqual(inv["planning_mode"], "current_month")
        self.assertTrue(inv["is_estimated"])

    def test_current_month_account_balance_fallback(self):
        """No bill_id-null transactions → fall back to Account.balance."""
        from app.services.credit_card_invoice import planning_invoice_for_month

        with Session(self.engine) as session:
            self._seed_credit(
                session,
                balance=Decimal("1500"),
                credit_balance_due_date=date(2026, 5, 17),
            )
            inv = planning_invoice_for_month(session, "2026-05", today=self.today)
        self.assertEqual(inv["source"], "account_balance")
        self.assertEqual(inv["amount"], 1500.0)

    # ----- future month -----

    def test_future_month_official_bill(self):
        from app.services.credit_card_invoice import planning_invoice_for_month

        with Session(self.engine) as session:
            self._seed_credit(
                session, balance=Decimal("999"), credit_balance_due_date=date(2026, 5, 17)
            )
            session.add(
                CreditCardBill(
                    id="bill-future",
                    account_id="cc1",
                    due_date=date(2026, 6, 10),
                    total_amount=Decimal("2500"),
                )
            )
            session.commit()
            inv = planning_invoice_for_month(session, "2026-06", today=self.today)
        self.assertEqual(inv["source"], "official_bill")
        self.assertEqual(inv["amount"], 2500.0)
        self.assertEqual(inv["bill_count"], 1)
        self.assertIn("2026-06-10", inv["due_dates"])
        self.assertFalse(inv["is_estimated"])

    def test_future_month_account_balance_due_month(self):
        """Account.balance is only used for a future month when the account's
        credit_balance_due_date falls in that month."""
        from app.services.credit_card_invoice import planning_invoice_for_month

        with Session(self.engine) as session:
            self._seed_credit(
                session, balance=Decimal("900"), credit_balance_due_date=date(2026, 6, 17)
            )
            inv = planning_invoice_for_month(session, "2026-06", today=self.today)
        self.assertEqual(inv["source"], "account_balance_due_month")
        self.assertEqual(inv["amount"], 900.0)

    def test_future_month_scheduled_installments(self):
        from app.services.credit_card_invoice import planning_invoice_for_month

        with Session(self.engine) as session:
            self._seed_credit(
                session, balance=Decimal("900"), credit_balance_due_date=date(2026, 5, 17)
            )
            session.add(
                Transaction(
                    id="parc-1",
                    account_id="cc1",
                    date=date(2026, 7, 15),
                    amount=Decimal("400"),
                    description="parcela",
                    category="Shopping",
                )
            )
            session.commit()
            inv = planning_invoice_for_month(session, "2026-07", today=self.today)
        self.assertEqual(inv["source"], "scheduled_installments")
        self.assertEqual(inv["amount"], 400.0)
        self.assertEqual(inv["transaction_count"], 1)

    def test_future_month_no_data_returns_none(self):
        from app.services.credit_card_invoice import planning_invoice_for_month

        with Session(self.engine) as session:
            self._seed_credit(
                session, balance=Decimal("900"), credit_balance_due_date=date(2026, 5, 17)
            )
            inv = planning_invoice_for_month(session, "2026-09", today=self.today)
        self.assertEqual(inv["source"], "none")
        self.assertEqual(inv["amount"], 0.0)

    # ----- past month -----

    def test_past_month_official_bill(self):
        from app.services.credit_card_invoice import planning_invoice_for_month

        with Session(self.engine) as session:
            self._seed_credit(session)
            session.add(
                CreditCardBill(
                    id="bill-past",
                    account_id="cc1",
                    due_date=date(2026, 4, 15),
                    total_amount=Decimal("777"),
                )
            )
            session.commit()
            inv = planning_invoice_for_month(session, "2026-04", today=self.today)
        self.assertEqual(inv["source"], "official_bill")
        self.assertEqual(inv["amount"], 777.0)

    def test_past_month_transaction_fallback(self):
        from app.services.credit_card_invoice import planning_invoice_for_month

        with Session(self.engine) as session:
            self._seed_credit(session)
            session.add(
                Transaction(
                    id="t-past",
                    account_id="cc1",
                    date=date(2026, 4, 10),
                    amount=Decimal("220"),
                    description="compra",
                    category="Shopping",
                )
            )
            session.commit()
            inv = planning_invoice_for_month(session, "2026-04", today=self.today)
        self.assertEqual(inv["source"], "transaction_fallback")
        self.assertEqual(inv["amount"], 220.0)

    # ----- no data / inactive -----

    def test_no_credit_card_data_returns_none(self):
        from app.services.credit_card_invoice import planning_invoice_for_month

        with Session(self.engine) as session:
            inv = planning_invoice_for_month(session, "2026-05", today=self.today)
        self.assertEqual(inv["source"], "none")
        self.assertEqual(inv["amount"], 0.0)
        self.assertEqual(inv["account_count"], 0)

    def test_inactive_accounts_ignored(self):
        from app.services.credit_card_invoice import planning_invoice_for_month

        with Session(self.engine) as session:
            session.add(
                Item(id="item-inactive", connector_id=200, status="UPDATED", is_active=False)
            )
            session.add(
                Account(
                    id="cc-inactive",
                    item_id="item-inactive",
                    name="CC",
                    type="CREDIT",
                    is_active=False,
                    balance=Decimal("5000"),
                    credit_balance_due_date=date(2026, 5, 17),
                )
            )
            session.commit()
            inv = planning_invoice_for_month(session, "2026-05", today=self.today)
        self.assertEqual(inv["source"], "none")
        self.assertEqual(inv["amount"], 0.0)
        self.assertEqual(inv["account_count"], 0)

    # ----- spending_capacity_summary integration -----

    def test_spending_capacity_includes_planning_invoice(self):
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)
            capacity = spending_capacity_summary(session, "2026-05", today=self.today)
        self.assertIn("planning_invoice", capacity)
        pinv = capacity["planning_invoice"]
        self.assertIn("source", pinv)
        self.assertIn("amount", pinv)
        for key in self.REQUIRED_KEYS:
            self.assertIn(key, pinv, f"planning_invoice missing key: {key}")

    def test_spending_capacity_compatibility_fields_present(self):
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)
            capacity = spending_capacity_summary(session, "2026-05", today=self.today)
        for field in (
            "card_invoice_official_total",
            "card_invoice_current_open_total",
            "card_invoice_current_open_source",
            "card_invoice_current_open_label",
            "future_card_obligation_total",
            "future_card_obligation_source",
            "future_card_obligation_display_month",
            "card_invoice_remaining_to_include",
            "credit_card_due_dates",
        ):
            self.assertIn(field, capacity, f"missing compat field: {field}")

    def test_spending_capacity_has_card_context_fields(self):
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)

            capacity = spending_capacity_summary(session, "2026-05", today=self.today)
            self.assertIn("card_open_balance_total", capacity)
            self.assertIn("credit_card_due_dates", capacity)
            # Current month: open-invoice estimate — CreditCardBill NOT used as source
            self.assertNotEqual(capacity["card_invoice_source"], "official_bill")
            self.assertEqual(capacity["card_invoice_source"], "open_invoice")
            # card_open_balance_total still reflects Account.balance snapshot
            self.assertEqual(capacity["card_open_balance_total"], 1500.0)
            self.assertIn("card_invoice_current_open_total", capacity)
            self.assertIn("card_invoice_cycle_start", capacity)
            self.assertIn("card_invoice_cycle_end", capacity)
            self.assertIn("card_invoice_transaction_count", capacity)

    def test_budget_available_unchanged_by_bill_context(self):
        """Adding card context must not double-count against budget_available_to_spend."""
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)

            capacity = spending_capacity_summary(session, "2026-05", today=self.today)
            self.assertIn("budget_available_to_spend", capacity)
            self.assertNotEqual(
                capacity["budget_available_to_spend"],
                capacity["budget_available_to_spend"] - capacity["card_invoice_official_total"],
            )

    def test_spending_capacity_future_month_not_contaminated_by_account_balance(self):
        """spending_capacity_summary for a NON-vigente future month must not carry
        the current Account.balance into card_invoice_official_total / remaining.

        Queries 2026-07 (today=2026-05-28 → vigente month is 2026-06, so July is
        a plain future month). The forming-cycle "fatura vigente" logic only
        applies to the vigente month, so July keeps the pure future-tier
        behaviour: no bill, no July-dated transactions → source = "none"."""
        from app.services.spending_capacity import spending_capacity_summary

        self.fake_pluggy.bills_supported = False
        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)
            acc = session.get(Account, "credit-1")
            balance = float(acc.balance)

            capacity = spending_capacity_summary(session, "2026-07", today=self.today)

        # July is not the vigente month and has no bill/transactions → "none".
        self.assertEqual(capacity["card_invoice_source"], "none")
        # The official total must NOT equal Account.balance
        self.assertNotEqual(capacity["card_invoice_official_total"], balance)
        # No July card transactions exist → gross = 0, official = 0, gap = 0
        self.assertEqual(capacity["card_invoice_gross_total"], 0.0)
        self.assertEqual(capacity["card_invoice_official_total"], 0.0)
        self.assertEqual(capacity["card_invoice_remaining_to_include"], 0.0)

    def test_vigente_month_uses_forming_cycle_transactions(self):
        """The vigente month (next calendar month) reflects the forming-cycle
        invoice computed from real transactions, not a frozen Account.balance
        snapshot or a premature official bill.

        today=2026-05-28, close_date=2026-05-10 → today is past close, so the
        forming cycle is 2026-05-11 – 2026-06-10 (due in June, the vigente
        month). The synced credit-buy (2026-05-28, +1500) is inside that cycle
        and is counted; source = "active_open_invoice_transactions"."""
        from app.services.spending_capacity import spending_capacity_summary

        # No official bill so we prove the value comes from transactions.
        self.fake_pluggy.bills_supported = False
        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)

            capacity = spending_capacity_summary(session, "2026-06", today=self.today)

        self.assertEqual(capacity["planning_mode"], "future_month")
        self.assertEqual(capacity["card_invoice_source"], "active_open_invoice_transactions")
        # The +1500 purchase in the forming cycle → +1500 invoice.
        self.assertEqual(capacity["card_invoice_official_total"], 1500.0)
        self.assertEqual(capacity["future_card_obligation_total"], 1500.0)

    def test_vigente_forming_invoice_overrides_stale_account_balance(self):
        """Regression for the "frozen for 2 weeks" bug: when today is past the
        close_date, recent purchases in the newly-opened cycle must be reflected
        in the vigente invoice instead of the stale Account.balance snapshot."""
        from app.services.spending_capacity import spending_capacity_summary

        self.fake_pluggy.bills_supported = False
        with Session(self.engine) as session:
            self._seed_item(session)
            sync_service.sync_item("item-1", session)
            # Simulate a fresh purchase in the newly-opened cycle (after close).
            session.add(
                Transaction(
                    id="fresh-buy",
                    account_id="credit-1",
                    date=date(2026, 5, 29),
                    amount=Decimal("200"),
                    description="Compra recente",
                    category="Shopping",
                )
            )
            session.commit()
            balance = float(session.get(Account, "credit-1").balance)

            capacity = spending_capacity_summary(session, "2026-06", today=self.today)

        # Forming cycle (2026-05-11 – 2026-06-10) holds credit-buy (1500) and
        # fresh-buy (200) → 1700, which differs from the frozen balance (1500).
        self.assertEqual(capacity["card_invoice_source"], "active_open_invoice_transactions")
        self.assertEqual(capacity["card_invoice_official_total"], 1700.0)
        self.assertNotEqual(capacity["card_invoice_official_total"], balance)


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
            session.add(Item(id="item-1", connector_id=1, connector_name="Test", status="UPDATED"))
            session.add(Account(id="credit-1", item_id="item-1", name="Card", type="CREDIT"))
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
