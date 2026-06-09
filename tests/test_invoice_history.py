"""Tests for credit-card invoice history month attribution.

Covers:
A. invoice_month_from_payment helper
B. credit_card_payments_monthly_summary attributes payments by invoice month
C. May 2026 appears when the payment is on 2026-04-29
D. April 2026 does not claim the April-29 payment as its own invoice
E. Historico page still loads
"""

import datetime
import unittest
from decimal import Decimal
from typing import Optional
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import Account, CreditCardInvoiceMonth, Item, MonthlyBalanceMonth, Transaction
from app.services.history import (
    credit_card_payments_monthly_summary,
    monthly_balance_summary,
)
from app.services.invoice_month import invoice_month_from_payment
from app.services.snapshots import (
    refresh_credit_card_invoice_snapshots,
    refresh_monthly_balance_snapshots,
)
from app.services.transactions import credit_card_payment_transactions


ITEM_ID = "item-hist-test"
CC_ACCOUNT_ID = "cc-hist-test"
BANK_ACCOUNT_ID = "bank-hist-test"


def _make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _seed_base(session: Session, due_date: Optional[datetime.date] = None) -> None:
    session.add(
        Item(
            id=ITEM_ID,
            connector_id=1,
            connector_name="Test",
            status="UPDATED",
            is_active=True,
        )
    )
    session.add(
        Account(
            id=CC_ACCOUNT_ID,
            item_id=ITEM_ID,
            name="Visa",
            type="CREDIT",
            currency_code="BRL",
            is_active=True,
            balance=Decimal("0"),
            credit_balance_due_date=due_date,
        )
    )
    session.commit()


def _add_payment(
    session: Session,
    *,
    tx_id: str,
    payment_date: datetime.date,
    amount: Decimal,
    description: str = "PAGAMENTO COM SALDO",
    account_id: str = CC_ACCOUNT_ID,
) -> None:
    session.add(
        Transaction(
            id=tx_id,
            account_id=account_id,
            date=payment_date,
            amount=-abs(amount),  # payments are negative on credit card
            description=description,
            category="Credit card payment",
        )
    )
    session.commit()


def _add_bank_account(session: Session) -> None:
    session.add(
        Account(
            id=BANK_ACCOUNT_ID,
            item_id=ITEM_ID,
            name="itau",
            type="BANK",
            currency_code="BRL",
            is_active=True,
            balance=Decimal("0"),
        )
    )
    session.commit()


def _add_bank_transaction(
    session: Session,
    *,
    tx_id: str,
    payment_date: datetime.date,
    amount: Decimal,
    description: str,
    category: str,
) -> None:
    session.add(
        Transaction(
            id=tx_id,
            account_id=BANK_ACCOUNT_ID,
            date=payment_date,
            amount=-abs(amount),
            description=description,
            category=category,
        )
    )
    session.commit()


def _add_income_transaction(
    session: Session,
    *,
    tx_id: str,
    transaction_date: datetime.date,
    amount: Decimal,
) -> None:
    session.add(
        Transaction(
            id=tx_id,
            account_id=BANK_ACCOUNT_ID,
            date=transaction_date,
            amount=abs(amount),
            description="Salary",
            category="Salary",
        )
    )
    session.commit()


class TestInvoiceMonthFromPayment(unittest.TestCase):
    """A. invoice_month_from_payment helper."""

    def test_payment_before_due_date_maps_to_same_month(self):
        # Payment on May 3, due_day=4 → candidate May 4 ≥ May 3 → 2026-05
        result = invoice_month_from_payment(datetime.date(2026, 5, 3), due_day=4)
        self.assertEqual(result, "2026-05")

    def test_payment_on_due_date_maps_to_same_month(self):
        # Payment on May 4, due_day=4 → candidate May 4 ≥ May 4 → 2026-05
        result = invoice_month_from_payment(datetime.date(2026, 5, 4), due_day=4)
        self.assertEqual(result, "2026-05")

    def test_payment_after_due_date_maps_to_next_month(self):
        # Payment on Apr 29, due_day=4 → candidate Apr 4 < Apr 29 → next = 2026-05
        result = invoice_month_from_payment(datetime.date(2026, 4, 29), due_day=4)
        self.assertEqual(result, "2026-05")

    def test_payment_at_month_end_maps_to_next_month(self):
        # Payment on Dec 31, due_day=6 → candidate Dec 6 < Dec 31 → next = 2027-01
        result = invoice_month_from_payment(datetime.date(2026, 12, 31), due_day=6)
        self.assertEqual(result, "2027-01")

    def test_year_boundary_correct(self):
        # Payment on Nov 30, due_day=5 → candidate Nov 5 < Nov 30 → next = 2026-12
        result = invoice_month_from_payment(datetime.date(2026, 11, 30), due_day=5)
        self.assertEqual(result, "2026-12")

    def test_payment_on_first_of_month_before_due(self):
        # Payment on May 1, due_day=6 → candidate May 6 ≥ May 1 → 2026-05
        result = invoice_month_from_payment(datetime.date(2026, 5, 1), due_day=6)
        self.assertEqual(result, "2026-05")

    def test_payment_after_due_day_6_maps_to_june(self):
        result = invoice_month_from_payment(datetime.date(2026, 5, 30), due_day=6)
        self.assertEqual(result, "2026-06")

    def test_payment_after_due_day_4_maps_to_next_month(self):
        result = invoice_month_from_payment(datetime.date(2026, 5, 5), due_day=4)
        self.assertEqual(result, "2026-06")

    def test_due_day_31_uses_last_day_in_february(self):
        result = invoice_month_from_payment(datetime.date(2026, 2, 28), due_day=31)
        self.assertEqual(result, "2026-02")


class TestCreditCardPaymentsMonthly(unittest.TestCase):
    """B-D. Monthly summary attributes payments by invoice month."""

    def setUp(self):
        self.engine = _make_engine()

    def test_may_2026_shows_april_29_payment(self):
        """B+C. Payment on 2026-04-29 appears under 2026-05 (invoice month)."""
        with Session(self.engine) as session:
            _seed_base(session, due_date=datetime.date(2026, 5, 4))
            _add_payment(
                session,
                tx_id="pay-apr29",
                payment_date=datetime.date(2026, 4, 29),
                amount=Decimal("16120.06"),
            )
            result = credit_card_payments_monthly_summary(session, months=12)

        months_by_key = {m["month"]: m for m in result["months"]}
        may = months_by_key.get("2026-05")
        apr = months_by_key.get("2026-04")

        self.assertIsNotNone(may, "2026-05 must be in the result")
        self.assertEqual(may["count"], 1, "May must have 1 invoice payment")
        self.assertAlmostEqual(may["total"], 16120.06, places=2)
        tx = may["transactions"][0]
        self.assertEqual(tx["id"], "pay-apr29")
        self.assertEqual(tx["date"], "2026-04-29")
        self.assertEqual(tx["invoice_month"], "2026-05")

        # D. April must NOT claim this payment
        if apr:
            self.assertEqual(apr["count"], 0, "April must not claim the Apr-29 payment")
            self.assertAlmostEqual(apr["total"], 0.0, places=2)

    def test_payment_on_due_date_stays_in_same_month(self):
        """C variant. Payment exactly on due date belongs to the same month."""
        with Session(self.engine) as session:
            _seed_base(session, due_date=datetime.date(2026, 5, 4))
            _add_payment(
                session,
                tx_id="pay-may4",
                payment_date=datetime.date(2026, 5, 4),
                amount=Decimal("10000.00"),
            )
            result = credit_card_payments_monthly_summary(session, months=12)

        months_by_key = {m["month"]: m for m in result["months"]}
        may = months_by_key.get("2026-05")
        self.assertIsNotNone(may)
        self.assertEqual(may["count"], 1)
        self.assertEqual(may["transactions"][0]["invoice_month"], "2026-05")

    def test_payment_before_due_stays_in_same_month(self):
        """Payment a few days before due date stays in that month."""
        with Session(self.engine) as session:
            _seed_base(session, due_date=datetime.date(2026, 5, 4))
            _add_payment(
                session,
                tx_id="pay-may3",
                payment_date=datetime.date(2026, 5, 3),
                amount=Decimal("5000.00"),
            )
            result = credit_card_payments_monthly_summary(session, months=12)

        months_by_key = {m["month"]: m for m in result["months"]}
        may = months_by_key.get("2026-05")
        self.assertIsNotNone(may)
        self.assertEqual(may["count"], 1)
        self.assertEqual(may["transactions"][0]["invoice_month"], "2026-05")

    def test_may_window_includes_april_payment_before_due_date(self):
        with Session(self.engine) as session:
            _seed_base(session, due_date=datetime.date(2026, 5, 4))
            _add_payment(
                session,
                tx_id="pay-apr29-window",
                payment_date=datetime.date(2026, 4, 29),
                amount=Decimal("16120.06"),
            )
            with patch("app.services.history.date") as mock_date:
                mock_date.today.return_value = datetime.date(2026, 6, 9)
                mock_date.side_effect = lambda *args, **kwargs: datetime.date(
                    *args,
                    **kwargs,
                )
                result = credit_card_payments_monthly_summary(session, months=2)

        months_by_key = {m["month"]: m for m in result["months"]}
        may = months_by_key["2026-05"]
        june = months_by_key["2026-06"]
        self.assertEqual(may["count"], 1)
        self.assertAlmostEqual(may["total"], 16120.06, places=2)
        self.assertEqual(may["transactions"][0]["invoice_month"], "2026-05")
        self.assertEqual(june["count"], 0)

    def test_total_is_sum_of_all_payments(self):
        """Grand total is consistent across all bucketed transactions."""
        with Session(self.engine) as session:
            _seed_base(session, due_date=datetime.date(2026, 5, 4))
            _add_payment(
                session,
                tx_id="p1",
                payment_date=datetime.date(2026, 4, 29),
                amount=Decimal("1000.00"),
            )
            _add_payment(
                session,
                tx_id="p2",
                payment_date=datetime.date(2026, 5, 3),
                amount=Decimal("2000.00"),
            )
            result = credit_card_payments_monthly_summary(session, months=12)

        self.assertEqual(result["total_count"], 2)
        self.assertAlmostEqual(result["total"], 3000.0, places=2)

    def test_no_payments_returns_empty_months(self):
        """When no invoice payments exist all months have count=0."""
        with Session(self.engine) as session:
            _seed_base(session)
            result = credit_card_payments_monthly_summary(session, months=3)

        self.assertEqual(result["total_count"], 0)
        self.assertEqual(result["total"], 0.0)
        for m in result["months"]:
            self.assertEqual(m["count"], 0)

    def test_bank_itau_boleto_payment_is_included(self):
        with Session(self.engine) as session:
            _seed_base(session)
            _add_bank_account(session)
            _add_bank_transaction(
                session,
                tx_id="bank-itau-boleto",
                payment_date=datetime.date(2026, 5, 30),
                amount=Decimal("17131.28"),
                description="Pagamento de boleto ITAU UNIBANCO HOLDING S.A.",
                category="Investments",
            )
            payments = credit_card_payment_transactions(
                session,
                datetime.date(2026, 5, 1),
                datetime.date(2026, 5, 31),
            )

        self.assertEqual([tx.id for tx in payments], ["bank-itau-boleto"])

    def test_bank_claro_pix_payment_is_not_included(self):
        with Session(self.engine) as session:
            _seed_base(session)
            _add_bank_account(session)
            _add_bank_transaction(
                session,
                tx_id="bank-claro-pix",
                payment_date=datetime.date(2026, 5, 30),
                amount=Decimal("30.50"),
                description="Pagamento de Pix QR Code CLARO",
                category="Telecommunications",
            )
            payments = credit_card_payment_transactions(
                session,
                datetime.date(2026, 5, 1),
                datetime.date(2026, 5, 31),
            )

        self.assertEqual(payments, [])

    def test_bank_itau_boleto_payment_appears_in_june_summary(self):
        with Session(self.engine) as session:
            _seed_base(session)
            _add_bank_account(session)
            _add_bank_transaction(
                session,
                tx_id="bank-itau-june",
                payment_date=datetime.date(2026, 5, 30),
                amount=Decimal("17131.28"),
                description="Pagamento de boleto ITAU UNIBANCO HOLDING S.A.",
                category="Investments",
            )
            result = credit_card_payments_monthly_summary(session, months=12)

        months_by_key = {m["month"]: m for m in result["months"]}
        june = months_by_key.get("2026-06")
        self.assertIsNotNone(june, "2026-06 must be in the result")
        self.assertEqual(june["count"], 1)
        self.assertAlmostEqual(june["total"], 17131.28, places=2)
        self.assertEqual(june["transactions"][0]["id"], "bank-itau-june")
        self.assertEqual(june["transactions"][0]["invoice_month"], "2026-06")

    def test_bank_fallback_is_deduped_when_credit_payment_exists(self):
        with Session(self.engine) as session:
            _seed_base(session)
            _add_bank_account(session)
            _add_bank_transaction(
                session,
                tx_id="bank-itau-duplicate",
                payment_date=datetime.date(2026, 5, 30),
                amount=Decimal("17131.28"),
                description="Pagamento de boleto ITAU UNIBANCO HOLDING S.A.",
                category="Investments",
            )
            _add_payment(
                session,
                tx_id="credit-itau-duplicate",
                payment_date=datetime.date(2026, 6, 2),
                amount=Decimal("17131.28"),
            )
            payments = credit_card_payment_transactions(
                session,
                datetime.date(2026, 5, 1),
                datetime.date(2026, 6, 30),
            )

        self.assertEqual([tx.id for tx in payments], ["credit-itau-duplicate"])

    def test_existing_credit_invoice_payment_still_works(self):
        with Session(self.engine) as session:
            _seed_base(session)
            _add_payment(
                session,
                tx_id="credit-payment",
                payment_date=datetime.date(2026, 5, 30),
                amount=Decimal("1234.56"),
            )
            payments = credit_card_payment_transactions(
                session,
                datetime.date(2026, 5, 1),
                datetime.date(2026, 5, 31),
            )

        self.assertEqual([tx.id for tx in payments], ["credit-payment"])

    def test_snapshot_refresh_uses_invoice_month_for_before_due_payment(self):
        with Session(self.engine) as session:
            _seed_base(session, due_date=datetime.date(2026, 5, 4))
            _add_payment(
                session,
                tx_id="pay-apr29-snapshot",
                payment_date=datetime.date(2026, 4, 29),
                amount=Decimal("16120.06"),
            )
            with patch("app.services.snapshots.date") as mock_date:
                mock_date.today.return_value = datetime.date(2026, 6, 9)
                mock_date.side_effect = lambda *args, **kwargs: datetime.date(*args, **kwargs)
                refresh_credit_card_invoice_snapshots(session, months=2)

            may = session.get(CreditCardInvoiceMonth, "2026-05")
            april = session.get(CreditCardInvoiceMonth, "2026-04")

        self.assertIsNotNone(may)
        self.assertEqual(may.payment_count, 1)
        self.assertAlmostEqual(float(may.total), 16120.06, places=2)
        self.assertIsNone(april)

    def test_snapshot_refresh_uses_invoice_month_for_same_month_before_due_payment(self):
        with Session(self.engine) as session:
            _seed_base(session, due_date=datetime.date(2026, 5, 4))
            _add_payment(
                session,
                tx_id="pay-may3-snapshot",
                payment_date=datetime.date(2026, 5, 3),
                amount=Decimal("2000.00"),
            )
            with patch("app.services.snapshots.date") as mock_date:
                mock_date.today.return_value = datetime.date(2026, 6, 9)
                mock_date.side_effect = lambda *args, **kwargs: datetime.date(
                    *args,
                    **kwargs,
                )
                refresh_credit_card_invoice_snapshots(session, months=2)

            may = session.get(CreditCardInvoiceMonth, "2026-05")

        self.assertIsNotNone(may)
        self.assertEqual(may.payment_count, 1)
        self.assertAlmostEqual(float(may.total), 2000.00, places=2)

    def test_monthly_balance_snapshot_uses_invoice_month_for_paid_invoice(self):
        with Session(self.engine) as session:
            _seed_base(session, due_date=datetime.date(2026, 5, 4))
            _add_bank_account(session)
            _add_income_transaction(
                session,
                tx_id="income-may",
                transaction_date=datetime.date(2026, 5, 10),
                amount=Decimal("5000.00"),
            )
            _add_payment(
                session,
                tx_id="pay-apr29-balance",
                payment_date=datetime.date(2026, 4, 29),
                amount=Decimal("1000.00"),
            )
            with patch("app.services.snapshots.date") as mock_date:
                mock_date.today.return_value = datetime.date(2026, 6, 9)
                mock_date.side_effect = lambda *args, **kwargs: datetime.date(
                    *args,
                    **kwargs,
                )
                refresh_monthly_balance_snapshots(session, months=2)

            may = session.get(MonthlyBalanceMonth, "2026-05")
            april = session.get(MonthlyBalanceMonth, "2026-04")

        self.assertIsNotNone(may)
        self.assertIsNone(april)
        self.assertAlmostEqual(float(may.income), 5000.00, places=2)
        self.assertAlmostEqual(float(may.card_spend), 0.00, places=2)
        self.assertAlmostEqual(float(may.invoice_paid), 1000.00, places=2)
        self.assertAlmostEqual(float(may.net_by_purchase_month), 5000.00, places=2)
        self.assertAlmostEqual(float(may.net_cashflow), 4000.00, places=2)
        self.assertEqual(may.income_count, 1)
        self.assertEqual(may.invoice_payment_count, 1)

    def test_live_monthly_balance_matches_snapshot_invoice_month(self):
        with Session(self.engine) as session:
            _seed_base(session, due_date=datetime.date(2026, 5, 4))
            _add_bank_account(session)
            _add_income_transaction(
                session,
                tx_id="income-live-may",
                transaction_date=datetime.date(2026, 5, 10),
                amount=Decimal("5000.00"),
            )
            _add_payment(
                session,
                tx_id="pay-apr29-live",
                payment_date=datetime.date(2026, 4, 29),
                amount=Decimal("1000.00"),
            )
            with patch("app.services.history.date") as history_date:
                history_date.today.return_value = datetime.date(2026, 6, 9)
                history_date.side_effect = lambda *args, **kwargs: datetime.date(
                    *args,
                    **kwargs,
                )
                live = monthly_balance_summary(session, months=2)
            with patch("app.services.snapshots.date") as snapshots_date:
                snapshots_date.today.return_value = datetime.date(2026, 6, 9)
                snapshots_date.side_effect = lambda *args, **kwargs: datetime.date(
                    *args,
                    **kwargs,
                )
                refresh_monthly_balance_snapshots(session, months=2)
            snapshot = session.get(MonthlyBalanceMonth, "2026-05")

        live_may = {m["month"]: m for m in live["months"]}["2026-05"]
        self.assertIsNotNone(snapshot)
        self.assertAlmostEqual(live_may["invoice_paid"], float(snapshot.invoice_paid), places=2)
        self.assertEqual(live_may["invoice_payment_count"], snapshot.invoice_payment_count)
        self.assertAlmostEqual(live_may["net_cashflow"], float(snapshot.net_cashflow), places=2)


class TestHistoricoPageLoads(unittest.TestCase):
    """E. Historico route still returns 200."""

    def setUp(self):
        self.engine = _make_engine()

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_get_session
        self.client = TestClient(app, follow_redirects=False)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_historico_page_loads(self):
        response = self.client.get("/historico")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_credit_card_payments_monthly_endpoint(self):
        response = self.client.get("/credit-card-payments/monthly?months=3")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("months", body)
        self.assertIn("total", body)
        self.assertIn("total_count", body)


if __name__ == "__main__":
    unittest.main()
