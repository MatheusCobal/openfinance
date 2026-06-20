import datetime
import unittest
from decimal import Decimal
from typing import Optional

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import Account, CreditCardBill, Item, Transaction
from app.services.credit_card_invoice import planning_invoice_for_month


ITEM_ID = "item-active"
ACCOUNT_ID = "cc-active"


class CreditCardInvoicePaymentStatusTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

    def _seed_credit_account(
        self,
        session: Session,
        *,
        item_id: str = ITEM_ID,
        account_id: str = ACCOUNT_ID,
        item_active: bool = True,
        account_active: bool = True,
    ) -> None:
        session.add(
            Item(
                id=item_id,
                connector_id=1,
                connector_name="Test",
                status="UPDATED",
                is_active=item_active,
            )
        )
        session.add(
            Account(
                id=account_id,
                item_id=item_id,
                name="Visa",
                type="CREDIT",
                currency_code="BRL",
                is_active=account_active,
            )
        )
        session.commit()

    def _add_bill(
        self,
        session: Session,
        *,
        total_amount: Decimal = Decimal("1000.00"),
        payments_total=None,
        account_id: str = ACCOUNT_ID,
    ) -> None:
        session.add(
            CreditCardBill(
                id=f"bill-{account_id}",
                account_id=account_id,
                due_date=datetime.date(2026, 5, 15),
                total_amount=total_amount,
                minimum_payment_amount=Decimal("100.00"),
                payments_total=payments_total,
            )
        )
        session.commit()

    def _invoice(self, session: Session):
        return planning_invoice_for_month(
            session,
            "2026-05",
            today=datetime.date(2026, 3, 20),
        )

    def test_paid_by_bill_payments_total(self):
        with Session(self.engine) as session:
            self._seed_credit_account(session)
            self._add_bill(session, payments_total=Decimal("1000.00"))

            invoice = self._invoice(session)

        self.assertEqual(invoice["payment_status"], "paid")
        self.assertEqual(invoice["payment_confidence"], "high")
        self.assertEqual(invoice["payment_source"], "bill_payments_total")
        self.assertEqual(invoice["paid_amount"], 1000.0)
        self.assertEqual(invoice["remaining_amount"], 0.0)
        self.assertEqual(invoice["matched_payment_transactions"], [])
        self.assertEqual(invoice["cards"][0]["payment_status"], "paid")

    def test_partial_payment_by_bill_payments_total(self):
        with Session(self.engine) as session:
            self._seed_credit_account(session)
            self._add_bill(session, payments_total=Decimal("400.00"))

            invoice = self._invoice(session)

        self.assertEqual(invoice["payment_status"], "partially_paid")
        self.assertEqual(invoice["payment_confidence"], "high")
        self.assertEqual(invoice["payment_source"], "bill_payments_total")
        self.assertEqual(invoice["paid_amount"], 400.0)
        self.assertEqual(invoice["remaining_amount"], 600.0)

    def test_unpaid_by_bill_payments_total(self):
        with Session(self.engine) as session:
            self._seed_credit_account(session)
            self._add_bill(session, payments_total=Decimal("0.00"))

            invoice = self._invoice(session)

        self.assertEqual(invoice["payment_status"], "unpaid")
        self.assertEqual(invoice["payment_confidence"], "medium")
        self.assertEqual(invoice["payment_source"], "bill_payments_total")
        self.assertEqual(invoice["paid_amount"], 0.0)
        self.assertEqual(invoice["remaining_amount"], 1000.0)

    def test_unknown_when_bill_payments_total_is_null(self):
        with Session(self.engine) as session:
            self._seed_credit_account(session)
            self._add_bill(session, payments_total=None)

            invoice = self._invoice(session)

        self.assertEqual(invoice["payment_status"], "unknown")
        self.assertEqual(invoice["payment_source"], "none")
        self.assertEqual(invoice["paid_amount"], 0.0)
        self.assertEqual(invoice["remaining_amount"], 1000.0)

    def test_paid_by_invoice_payment_transaction(self):
        with Session(self.engine) as session:
            self._seed_credit_account(session)
            self._add_bill(session, payments_total=None)
            session.add(
                Transaction(
                    id="pay-full",
                    account_id=ACCOUNT_ID,
                    date=datetime.date(2026, 5, 14),
                    amount=Decimal("-1000.00"),
                    description="Pagamento recebido",
                    category="Credit card payment",
                )
            )
            session.commit()

            invoice = self._invoice(session)

        self.assertEqual(invoice["payment_status"], "paid")
        self.assertEqual(invoice["payment_confidence"], "medium")
        self.assertEqual(invoice["payment_source"], "invoice_payment_transaction")
        self.assertEqual(invoice["paid_amount"], 1000.0)
        self.assertEqual(invoice["remaining_amount"], 0.0)
        self.assertEqual(len(invoice["matched_payment_transactions"]), 1)
        self.assertEqual(invoice["matched_payment_transactions"][0]["id"], "pay-full")

    def test_partial_by_invoice_payment_transaction(self):
        with Session(self.engine) as session:
            self._seed_credit_account(session)
            self._add_bill(session, payments_total=None)
            session.add(
                Transaction(
                    id="pay-partial",
                    account_id=ACCOUNT_ID,
                    date=datetime.date(2026, 5, 14),
                    amount=Decimal("-300.00"),
                    description="Pagamento recebido",
                    category="Card payments",
                )
            )
            session.commit()

            invoice = self._invoice(session)

        self.assertEqual(invoice["payment_status"], "partially_paid")
        self.assertEqual(invoice["payment_source"], "invoice_payment_transaction")
        self.assertEqual(invoice["paid_amount"], 300.0)
        self.assertEqual(invoice["remaining_amount"], 700.0)

    def test_no_invoice_returns_not_applicable(self):
        with Session(self.engine) as session:
            invoice = planning_invoice_for_month(
                session,
                "2026-05",
                today=datetime.date(2026, 3, 20),
            )

        self.assertEqual(invoice["source"], "none")
        self.assertEqual(invoice["payment_status"], "not_applicable")
        self.assertEqual(invoice["payment_confidence"], "none")
        self.assertEqual(invoice["payment_source"], "none")
        self.assertEqual(invoice["paid_amount"], 0.0)
        self.assertEqual(invoice["remaining_amount"], 0.0)
        self.assertEqual(invoice["matched_payment_transactions"], [])

    def test_planning_endpoint_includes_payment_status(self):
        def override_get_session():
            with Session(self.engine) as session:
                yield session

        with Session(self.engine) as session:
            self._seed_credit_account(session)
            self._add_bill(session, payments_total=Decimal("1000.00"))

        app.dependency_overrides[get_session] = override_get_session
        try:
            response = TestClient(app).get("/planning/month/2026-05")
        finally:
            app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        invoice = response.json()["credit_card_invoice"]
        self.assertEqual(invoice["payment_status"], "paid")
        self.assertIn("remaining_amount", invoice)
        self.assertIn("payment_source", invoice)

    def test_inactive_account_payment_does_not_pay_active_invoice(self):
        with Session(self.engine) as session:
            self._seed_credit_account(session)
            self._seed_credit_account(
                session,
                item_id="item-inactive",
                account_id="cc-inactive",
                item_active=False,
                account_active=False,
            )
            self._add_bill(session, payments_total=None)
            session.add(
                Transaction(
                    id="inactive-payment",
                    account_id="cc-inactive",
                    date=datetime.date(2026, 5, 14),
                    amount=Decimal("-1000.00"),
                    description="Pagamento recebido",
                    category="Credit card payment",
                )
            )
            session.commit()

            invoice = self._invoice(session)

        self.assertEqual(invoice["payment_status"], "unknown")
        self.assertEqual(invoice["payment_source"], "none")
        self.assertEqual(invoice["matched_payment_transactions"], [])


class StaleDueDateGuardTest(unittest.TestCase):
    """Tests for Task 1 & 2: stale account balance due date must be ignored."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

    def _seed_item_and_account(
        self,
        session: Session,
        *,
        item_id: str = "item-test",
        account_id: str = "cc-test",
        balance: Decimal = Decimal("24712.95"),
        due_date: Optional[datetime.date] = None,
    ) -> None:
        session.add(
            Item(
                id=item_id,
                connector_id=1,
                connector_name="Test",
                status="UPDATED",
                is_active=True,
            )
        )
        session.add(
            Account(
                id=account_id,
                item_id=item_id,
                name="Visa",
                type="CREDIT",
                currency_code="BRL",
                is_active=True,
                balance=balance,
                credit_balance_due_date=due_date,
            )
        )
        session.commit()

    # A. Stale account balance due date is ignored for the selected month
    def test_stale_due_date_ignored_for_selected_month(self):
        """Account due date 2026-05-04 must not drive the June 2026 invoice."""
        with Session(self.engine) as session:
            self._seed_item_and_account(
                session,
                balance=Decimal("24712.95"),
                due_date=datetime.date(2026, 5, 4),
            )
            invoice = planning_invoice_for_month(
                session,
                "2026-06",
                today=datetime.date(2026, 6, 1),
            )

        self.assertNotEqual(invoice["amount"], 24712.95, "stale balance must not be invoice amount")
        self.assertNotIn(
            "2026-05-04", invoice["due_dates"], "stale due date must not appear in due_dates"
        )
        self.assertNotEqual(
            invoice["source"],
            "account_balance",
            "source must not be account_balance when due date is stale",
        )
        self.assertTrue(
            invoice.get("account_balance_due_date_is_stale"), "must flag stale due date"
        )
        self.assertEqual(invoice.get("account_balance_due_date"), "2026-05-04")

    # B. Previous-cycle payment is not matched when due date is stale
    def test_previous_cycle_payment_not_matched(self):
        """Payment from 2026-04-29 must not be matched to the June 2026 invoice."""
        with Session(self.engine) as session:
            self._seed_item_and_account(
                session,
                balance=Decimal("24712.95"),
                due_date=datetime.date(2026, 5, 4),
            )
            # Payment that belonged to the previous invoice cycle
            session.add(
                Transaction(
                    id="prev-cycle-payment",
                    account_id="cc-test",
                    date=datetime.date(2026, 4, 29),
                    amount=Decimal("-16120.06"),
                    description="PAGAMENTO COM SALDO",
                    category="Credit card payment",
                )
            )
            session.commit()

            invoice = planning_invoice_for_month(
                session,
                "2026-06",
                today=datetime.date(2026, 6, 1),
            )

        matched_ids = [tx["id"] for tx in invoice["matched_payment_transactions"]]
        self.assertNotIn(
            "prev-cycle-payment", matched_ids, "April payment must not match June invoice"
        )
        self.assertNotEqual(
            invoice["payment_status"],
            "partially_paid",
            "must not be partially_paid from prior-cycle payment",
        )

    # C. Valid due-month account balance is still accepted
    def test_valid_due_date_in_month_is_accepted(self):
        """When account due date is 2026-06-06 and selected month is 2026-06, use the balance."""
        with Session(self.engine) as session:
            self._seed_item_and_account(
                session,
                balance=Decimal("5000.00"),
                due_date=datetime.date(2026, 6, 6),
            )
            invoice = planning_invoice_for_month(
                session,
                "2026-06",
                today=datetime.date(2026, 6, 1),
            )

        self.assertEqual(invoice["source"], "account_balance")
        self.assertIn("2026-06-06", invoice["due_dates"])
        self.assertEqual(invoice["amount"], 5000.0)
        self.assertFalse(invoice.get("account_balance_due_date_is_stale", False))

    # D. Official bill remains highest priority for future month
    def test_official_bill_takes_priority_over_account_balance(self):
        """Official CreditCardBill in the selected month overrides account balance."""
        with Session(self.engine) as session:
            self._seed_item_and_account(
                session,
                account_id="cc-test",
                balance=Decimal("9999.00"),
                due_date=datetime.date(2026, 7, 6),
            )
            session.add(
                CreditCardBill(
                    id="bill-july",
                    account_id="cc-test",
                    due_date=datetime.date(2026, 7, 6),
                    total_amount=Decimal("7500.00"),
                    minimum_payment_amount=Decimal("500.00"),
                    payments_total=Decimal("7500.00"),
                )
            )
            session.commit()

            invoice = planning_invoice_for_month(
                session,
                "2026-07",
                today=datetime.date(2026, 5, 1),
            )

        self.assertEqual(invoice["source"], "official_bill")
        self.assertEqual(invoice["amount"], 7500.0)
        self.assertEqual(invoice["payment_status"], "paid")
        self.assertIn("2026-07-06", invoice["due_dates"])

    # F. Default planning month helper
    def test_default_planning_month_is_next_calendar_month(self):
        """Backend: next month from a given date is the expected planning default."""

        def default_planning_month(today: datetime.date) -> str:
            y, m = today.year, today.month
            if m == 12:
                return f"{y + 1}-01"
            return f"{y}-{m + 1:02d}"

        self.assertEqual(default_planning_month(datetime.date(2026, 6, 1)), "2026-07")
        self.assertEqual(default_planning_month(datetime.date(2026, 12, 15)), "2027-01")
        self.assertEqual(default_planning_month(datetime.date(2025, 11, 30)), "2025-12")


if __name__ == "__main__":
    unittest.main()
