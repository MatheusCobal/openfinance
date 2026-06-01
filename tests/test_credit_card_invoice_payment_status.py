import datetime
import unittest
from decimal import Decimal

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
            today=datetime.date(2026, 4, 20),
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
                today=datetime.date(2026, 4, 20),
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


if __name__ == "__main__":
    unittest.main()
