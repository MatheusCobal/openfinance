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
from pathlib import Path
from typing import Optional
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import (
    Account,
    CreditCardBill,
    CreditCardInvoiceMonth,
    Item,
    MonthlyBalanceMonth,
    Transaction,
)
from app.services.history import (
    bank_income_history_summary,
    credit_card_invoice_purchases_monthly_summary,
    credit_card_payments_monthly_summary,
    credit_card_payments_history_summary,
    monthly_balance_summary,
    monthly_balance_history_summary,
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


def _add_card_transaction(
    session: Session,
    *,
    tx_id: str,
    transaction_date: datetime.date,
    amount: Decimal,
    description: str,
    category: str,
    account_id: str = CC_ACCOUNT_ID,
    internal_category: Optional[str] = None,
    cashflow_type: Optional[str] = None,
    classification_source: Optional[str] = None,
    classification_confidence: Optional[str] = None,
    classification_rule_key: Optional[str] = None,
    ignored_from_totals: bool = False,
    is_user_overridden: bool = False,
) -> None:
    session.add(
        Transaction(
            id=tx_id,
            account_id=account_id,
            date=transaction_date,
            amount=amount,
            description=description,
            category=category,
            pluggy_raw_category=category,
            internal_category=internal_category,
            cashflow_type=cashflow_type,
            classification_source=classification_source,
            classification_confidence=classification_confidence,
            classification_rule_key=classification_rule_key,
            ignored_from_totals=ignored_from_totals,
            is_user_overridden=is_user_overridden,
        )
    )
    session.commit()


def _add_credit_card_bill(
    session: Session,
    *,
    bill_id: str,
    due_date: datetime.date,
    total: Decimal,
    account_id: str = CC_ACCOUNT_ID,
) -> None:
    session.add(
        CreditCardBill(
            id=bill_id,
            account_id=account_id,
            due_date=due_date,
            total_amount=total,
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


class TestCreditCardHistoryMonthly(unittest.TestCase):
    """Credit-card history summaries, including classified invoice purchases."""

    def setUp(self):
        self.engine = _make_engine()

    def test_groups_card_purchases_by_internal_category_and_average(self):
        with Session(self.engine) as session:
            _seed_base(session)
            _add_bank_account(session)
            _add_card_transaction(
                session,
                tx_id="food-apr",
                transaction_date=datetime.date(2026, 4, 10),
                amount=Decimal("-60.00"),
                description="Mercado abril",
                category="Food",
                internal_category="Alimentação",
                cashflow_type="expense",
                classification_source="pluggy_rule",
                classification_confidence="high",
                classification_rule_key="pluggy_raw_category:Food",
            )
            _add_card_transaction(
                session,
                tx_id="food-may",
                transaction_date=datetime.date(2026, 5, 10),
                amount=Decimal("-120.00"),
                description="Mercado maio",
                category="Food",
                internal_category="Alimentação",
                cashflow_type="expense",
                classification_source="pluggy_rule",
                classification_confidence="high",
                classification_rule_key="pluggy_raw_category:Food",
            )
            _add_card_transaction(
                session,
                tx_id="food-jun",
                transaction_date=datetime.date(2026, 6, 10),
                amount=Decimal("-100.00"),
                description="Mercado junho",
                category="Food",
                internal_category="Alimentação",
                cashflow_type="expense",
                classification_source="pluggy_rule",
                classification_confidence="high",
                classification_rule_key="pluggy_raw_category:Food",
            )
            _add_card_transaction(
                session,
                tx_id="manual-jun",
                transaction_date=datetime.date(2026, 6, 11),
                amount=Decimal("-40.00"),
                description="Taxi manual",
                category="Transport",
                internal_category="Transporte",
                cashflow_type="expense",
                classification_source="manual_override",
                classification_confidence="high",
                classification_rule_key="manual_override",
                is_user_overridden=True,
            )
            _add_card_transaction(
                session,
                tx_id="user-rule-jun",
                transaction_date=datetime.date(2026, 6, 12),
                amount=Decimal("-30.00"),
                description="Pet rule",
                category="Shopping",
                internal_category="Pet",
                cashflow_type="expense",
                classification_source="user_rule",
                classification_confidence="high",
                classification_rule_key="user_rule:1",
            )
            _add_card_transaction(
                session,
                tx_id="payment-jun",
                transaction_date=datetime.date(2026, 6, 13),
                amount=Decimal("-999.00"),
                description="Pagamento recebido",
                category="Credit card payment",
                internal_category="Pagamento de cartão",
                cashflow_type="credit_card_payment",
                classification_source="pluggy_rule",
                classification_confidence="high",
                classification_rule_key="pluggy_raw_category:Credit card payment",
                ignored_from_totals=True,
            )
            _add_card_transaction(
                session,
                tx_id="transfer-jun",
                transaction_date=datetime.date(2026, 6, 13),
                amount=Decimal("-25.00"),
                description="Transfer interna",
                category="Transfer - Internal",
                internal_category="Transferências",
                cashflow_type="transfer",
                classification_source="pluggy_rule",
                classification_confidence="high",
                classification_rule_key="pluggy_raw_category:Transfer - Internal",
                ignored_from_totals=True,
            )
            _add_card_transaction(
                session,
                tx_id="refund-jun",
                transaction_date=datetime.date(2026, 6, 14),
                amount=Decimal("-15.00"),
                description="Estorno",
                category="Refund",
                internal_category="Estorno",
                cashflow_type="refund",
                classification_source="pluggy_rule",
                classification_confidence="high",
                classification_rule_key="pluggy_raw_category:Refund",
            )
            _add_card_transaction(
                session,
                tx_id="ignored-jun",
                transaction_date=datetime.date(2026, 6, 14),
                amount=Decimal("-10.00"),
                description="Compra ignorada",
                category="Food",
                internal_category="Alimentação",
                cashflow_type="expense",
                classification_source="manual_override",
                classification_confidence="high",
                classification_rule_key="manual_override",
                ignored_from_totals=True,
                is_user_overridden=True,
            )
            _add_card_transaction(
                session,
                tx_id="bank-pix-jun",
                transaction_date=datetime.date(2026, 6, 14),
                amount=Decimal("-70.00"),
                description="Pix mercado",
                category="Food",
                account_id=BANK_ACCOUNT_ID,
                internal_category="Alimentação",
                cashflow_type="expense",
                classification_source="pluggy_rule",
                classification_confidence="high",
                classification_rule_key="pluggy_raw_category:Food",
            )

            with patch("app.services.history.date") as history_date:
                history_date.today.return_value = datetime.date(2026, 6, 15)
                history_date.side_effect = lambda *args, **kwargs: datetime.date(
                    *args,
                    **kwargs,
                )
                result = credit_card_invoice_purchases_monthly_summary(session, months=3)

        months = {month["month"]: month for month in result["months"]}
        june = months["2026-06"]

        self.assertAlmostEqual(june["total"], 170.0, places=2)
        self.assertEqual(june["count"], 3)
        tx_ids = {tx["id"] for tx in june["transactions"]}
        self.assertEqual({"food-jun", "manual-jun", "user-rule-jun"}, tx_ids)
        self.assertNotIn("payment-jun", tx_ids)
        self.assertNotIn("transfer-jun", tx_ids)
        self.assertNotIn("refund-jun", tx_ids)
        self.assertNotIn("ignored-jun", tx_ids)
        self.assertNotIn("bank-pix-jun", tx_ids)

        by_category = {category["name"]: category for category in june["categories"]}
        self.assertEqual(set(by_category), {"Alimentação", "Transporte", "Pet"})
        self.assertAlmostEqual(by_category["Alimentação"]["total"], 100.0, places=2)
        self.assertAlmostEqual(by_category["Alimentação"]["average_12m"], 90.0, places=2)
        self.assertEqual(by_category["Alimentação"]["average_months_used"], 2)
        self.assertAlmostEqual(
            by_category["Alimentação"]["difference_from_average"],
            10.0,
            places=2,
        )
        self.assertAlmostEqual(
            by_category["Alimentação"]["difference_percent"],
            11.111111,
            places=5,
        )
        self.assertEqual(by_category["Transporte"]["transactions"][0]["classification_source"], "manual_override")
        self.assertEqual(by_category["Pet"]["transactions"][0]["classification_source"], "user_rule")

    def test_historical_month_uses_official_bill_as_display_total(self):
        with Session(self.engine) as session:
            _seed_base(session, due_date=datetime.date(2026, 6, 8))
            account = session.get(Account, CC_ACCOUNT_ID)
            account.balance = Decimal("28619.60")
            session.add(account)
            session.commit()
            _add_credit_card_bill(
                session,
                bill_id="bill-jun-official",
                due_date=datetime.date(2026, 6, 8),
                total=Decimal("17131.28"),
            )
            _add_card_transaction(
                session,
                tx_id="classified-jun",
                transaction_date=datetime.date(2026, 6, 2),
                amount=Decimal("-164.00"),
                description="Compra classificada",
                category="Food",
                internal_category="Alimentação",
                cashflow_type="expense",
                classification_source="pluggy_rule",
                classification_confidence="high",
                classification_rule_key="pluggy_raw_category:Food",
            )
            with patch("app.services.history.date") as history_date:
                history_date.today.return_value = datetime.date(2026, 6, 10)
                history_date.side_effect = lambda *args, **kwargs: datetime.date(
                    *args,
                    **kwargs,
                )
                result = credit_card_invoice_purchases_monthly_summary(session, months=2)

        months = {month["month"]: month for month in result["months"]}
        june = months["2026-06"]

        self.assertEqual(result["current_invoice_month"], "2026-07")
        self.assertFalse(june["is_current_invoice"])
        self.assertEqual(june["invoice_total_source"], "pluggy_official_bill")
        self.assertAlmostEqual(june["invoice_display_total"], 17131.28, places=2)
        self.assertAlmostEqual(june["total"], 17131.28, places=2)
        self.assertAlmostEqual(june["official_bill_total"], 17131.28, places=2)
        self.assertAlmostEqual(june["classified_purchase_total"], 164.0, places=2)
        self.assertNotEqual(june["invoice_display_total"], june["classified_purchase_total"])
        self.assertAlmostEqual(
            june["classified_purchase_difference_from_invoice"],
            -16967.28,
            places=2,
        )
        self.assertEqual(june["categories"][0]["name"], "Alimentação")
        self.assertAlmostEqual(june["categories"][0]["total"], 164.0, places=2)

    def test_current_invoice_uses_dashboard_total_not_official_bill(self):
        with Session(self.engine) as session:
            _seed_base(session, due_date=datetime.date(2026, 6, 8))
            account = session.get(Account, CC_ACCOUNT_ID)
            account.balance = Decimal("28619.60")
            session.add(account)
            session.commit()
            _add_credit_card_bill(
                session,
                bill_id="bill-jun-closed",
                due_date=datetime.date(2026, 6, 8),
                total=Decimal("17131.28"),
            )
            _add_credit_card_bill(
                session,
                bill_id="bill-jul-premature",
                due_date=datetime.date(2026, 7, 8),
                total=Decimal("9999.00"),
            )
            with patch("app.services.history.date") as history_date:
                history_date.today.return_value = datetime.date(2026, 6, 10)
                history_date.side_effect = lambda *args, **kwargs: datetime.date(
                    *args,
                    **kwargs,
                )
                result = credit_card_invoice_purchases_monthly_summary(session, months=1)

        july = result["months"][0]

        self.assertEqual(july["month"], "2026-07")
        self.assertTrue(july["is_current_invoice"])
        self.assertEqual(july["invoice_total_source"], "dashboard_current_invoice")
        self.assertEqual(july["dashboard_current_invoice_source"], "adjusted_account_balance")
        self.assertAlmostEqual(july["invoice_display_total"], 11488.32, places=2)
        self.assertAlmostEqual(july["total"], 11488.32, places=2)
        self.assertAlmostEqual(july["official_bill_total"], 9999.0, places=2)
        self.assertNotEqual(july["invoice_display_total"], july["official_bill_total"])

    def test_missing_historical_official_bill_uses_marked_classified_fallback(self):
        with Session(self.engine) as session:
            _seed_base(session)
            _add_card_transaction(
                session,
                tx_id="classified-missing-bill",
                transaction_date=datetime.date(2026, 6, 2),
                amount=Decimal("-44.00"),
                description="Compra sem bill oficial",
                category="Food",
                internal_category="Alimentação",
                cashflow_type="expense",
            )
            with patch("app.services.history.date") as history_date:
                history_date.today.return_value = datetime.date(2026, 6, 10)
                history_date.side_effect = lambda *args, **kwargs: datetime.date(
                    *args,
                    **kwargs,
                )
                result = credit_card_invoice_purchases_monthly_summary(session, months=2)

        june = {month["month"]: month for month in result["months"]}["2026-06"]

        self.assertEqual(june["invoice_total_source"], "missing_official_bill_fallback")
        self.assertIsNone(june["official_bill_total"])
        self.assertAlmostEqual(june["invoice_display_total"], 44.0, places=2)
        self.assertAlmostEqual(june["classified_purchase_total"], 44.0, places=2)

    def test_endpoint_returns_classified_invoice_payload(self):
        def override_get_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_get_session
        try:
            with Session(self.engine) as session:
                _seed_base(session)
                _add_card_transaction(
                    session,
                    tx_id="food-endpoint",
                    transaction_date=datetime.date(2026, 6, 10),
                    amount=Decimal("-25.00"),
                    description="Padaria",
                    category="Food",
                    internal_category="Alimentação",
                    cashflow_type="expense",
                    classification_source="pluggy_rule",
                    classification_confidence="high",
                    classification_rule_key="pluggy_raw_category:Food",
                )

            client = TestClient(app)
            with patch("app.services.history.date") as history_date:
                history_date.today.return_value = datetime.date(2026, 6, 10)
                history_date.side_effect = lambda *args, **kwargs: datetime.date(
                    *args,
                    **kwargs,
                )
                response = client.get("/credit-card-invoices/monthly", params={"months": 2})
        finally:
            app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["purchase_boundary"]["account_type"], "CREDIT")
        self.assertEqual(body["purchase_boundary"]["cashflow_type"], "expense")
        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["current_invoice_month"], "2026-07")
        months = {month["month"]: month for month in body["months"]}
        self.assertIn("invoice_display_total", months["2026-06"])
        self.assertIn("classified_purchase_total", months["2026-06"])
        self.assertEqual(months["2026-06"]["categories"][0]["name"], "Alimentação")

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


class TestHistorySummariesAreReadOnly(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def test_history_summary_functions_do_not_refresh_snapshots(self):
        with Session(self.engine) as session:
            with (
                patch(
                    "app.services.snapshots.refresh_credit_card_invoice_snapshots",
                ) as credit_refresh,
                patch("app.services.snapshots.refresh_bank_income_snapshots") as income_refresh,
                patch(
                    "app.services.snapshots.refresh_monthly_balance_snapshots"
                ) as balance_refresh,
            ):
                credit_card_payments_history_summary(session)
                bank_income_history_summary(session)
                monthly_balance_history_summary(session)

        credit_refresh.assert_not_called()
        income_refresh.assert_not_called()
        balance_refresh.assert_not_called()


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

    def test_historico_removes_income_tab_and_keeps_cashflow_tab(self):
        response = self.client.get("/historico")
        self.assertEqual(response.status_code, 200)
        html = response.text
        source = Path("frontend/src/pages/HistoricoPage.tsx").read_text(encoding="utf-8")

        self.assertNotIn("income-tab", html)
        self.assertNotIn("Receitas", source)
        self.assertNotIn("/bank-income/monthly", source)
        self.assertNotIn("/bank-income/exclusion-rules", source)
        self.assertIn("Entradas e saídas", source)
        self.assertIn("/bank-cashflow/monthly", Path("frontend/src/api/historico.ts").read_text())

    def test_historico_uses_invoice_display_total_for_invoice_values(self):
        response = self.client.get("/historico")
        self.assertEqual(response.status_code, 200)
        html = response.text
        source = Path("frontend/src/pages/HistoricoPage.tsx").read_text(encoding="utf-8")

        self.assertIn('<div id="root"></div>', html)
        self.assertIn("function invoiceDisplayTotal", source)
        self.assertIn("invoice_display_total", source)
        self.assertIn("data.months.map(invoiceDisplayTotal)", source)
        self.assertIn("classified_purchase_total", source)

    def test_historico_invoice_rows_show_source_not_purchase_count(self):
        source = Path("frontend/src/pages/HistoricoPage.tsx").read_text(encoding="utf-8")
        labels = Path("frontend/src/lib/labels.ts").read_text(encoding="utf-8")

        self.assertIn("Fatura oficial Pluggy", source)
        self.assertIn("Fatura vigente calculada", source)
        self.assertIn("Sem fatura oficial", source)
        self.assertIn("pluggy_official_bill: \"Fatura oficial Pluggy\"", labels)
        self.assertIn("dashboard_current_invoice: \"Fatura vigente calculada\"", labels)
        self.assertIn("missing_official_bill_fallback: \"Sem fatura oficial\"", labels)
        self.assertNotIn(
            "${formatMonthLong(active.month)} · "
            "${invoiceSourceLabel(active.invoice_total_source)} · "
            "${pluralCompras(active.count)}",
            source,
        )
        self.assertNotIn("<span>{pluralCompras(item.count)}</span>", source)

    def test_credit_card_payments_monthly_endpoint(self):
        response = self.client.get("/credit-card-payments/monthly?months=3")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("months", body)
        self.assertIn("total", body)
        self.assertIn("total_count", body)

    def test_bank_cashflow_monthly_endpoint_remains_available(self):
        response = self.client.get("/bank-cashflow/monthly?months=1")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("months", body)
        self.assertIn("summary", body)


if __name__ == "__main__":
    unittest.main()
