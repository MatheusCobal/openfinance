"""Sign-convention tests for credit-card spend/invoice flows.

Convention (validated against the synced Pluggy data):
  - card purchases are POSITIVE on CREDIT accounts;
  - invoice payments, refunds and cancellations are NEGATIVE.

These tests guarantee that:
  - purchases enter the open invoice / spend totals;
  - invoice payments never inflate the open invoice;
  - refunds reduce the open invoice (zero floor on the final total only)
    and are neutral in gross spend pickers;
  - the vigente invoice accepts only positive PENDING purchases.
"""

import datetime
import unittest
from decimal import Decimal

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models import Account, Item, Transaction
from app.services.classification import (
    TransactionClassification,
    TransactionClassifier,
    TransactionKind,
    card_invoice_signed_amount,
)
from app.services.credit_card_invoice import (
    planning_invoice_for_month,
    scheduled_installments_for_month,
)
from app.services.transaction_reports import invoice_summary
from app.services.transactions import (
    credit_card_spend_transactions,
    discretionary_spend_transactions,
)

ITEM_ID = "item-1"
CC_ID = "cc-1"

TODAY = datetime.date(2026, 6, 12)


def _make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _seed_credit_account(session: Session, **account_kwargs) -> None:
    session.add(Item(id=ITEM_ID, connector_id=1, connector_name="T", status="UPDATED"))
    defaults = dict(
        id=CC_ID,
        item_id=ITEM_ID,
        name="Card",
        type="CREDIT",
        currency_code="BRL",
        is_active=True,
    )
    defaults.update(account_kwargs)
    session.add(Account(**defaults))
    session.commit()


def _add_tx(
    session: Session,
    tx_id: str,
    tx_date: datetime.date,
    amount: str,
    description: str,
    category: str,
) -> None:
    session.add(
        Transaction(
            id=tx_id,
            account_id=CC_ID,
            date=tx_date,
            amount=Decimal(amount),
            description=description,
            category=category,
            status="PENDING",
        )
    )
    session.commit()


class CardClassificationSignTest(unittest.TestCase):
    """TransactionClassifier kinds under the standardized sign convention."""

    def setUp(self):
        self.engine = _make_engine()

    def _classify(self, amount: str, description: str, category: str):
        with Session(self.engine) as session:
            _seed_credit_account(session)
            _add_tx(session, "tx-1", TODAY, amount, description, category)
            classifier = TransactionClassifier.from_session(session)
            tx = session.get(Transaction, "tx-1")
            return classifier.classify(tx)

    def test_positive_expense_is_card_purchase(self):
        result = self._classify("80.00", "Restaurante", "Eating out")
        self.assertEqual(result.kind, TransactionKind.CARD_PURCHASE)
        self.assertTrue(result.is_card_purchase)
        self.assertFalse(result.is_card_refund)

    def test_negative_expense_is_card_refund_not_purchase(self):
        # Real-data shape: "CANC PARCELA SEM J01/12" arrives with the
        # original purchase category (Shopping) and a negative amount.
        result = self._classify("-103.11", "CANC PARCELA SEM J01/12", "Shopping")
        self.assertEqual(result.kind, TransactionKind.CARD_REFUND)
        self.assertFalse(result.is_card_purchase)
        self.assertTrue(result.is_card_refund)

    def test_invoice_payment_is_still_detected(self):
        result = self._classify("-1500.00", "Pagamento recebido", "Credit card payment")
        self.assertEqual(result.kind, TransactionKind.INVOICE_PAYMENT)
        self.assertTrue(result.is_invoice_payment)
        self.assertFalse(result.is_card_purchase)
        self.assertFalse(result.is_card_refund)

    def test_signed_amount_helper(self):
        purchase = TransactionClassification(
            kind=TransactionKind.CARD_PURCHASE, account_type="CREDIT"
        )
        refund = TransactionClassification(kind=TransactionKind.CARD_REFUND, account_type="CREDIT")
        payment = TransactionClassification(
            kind=TransactionKind.INVOICE_PAYMENT, account_type="CREDIT"
        )

        def tx(amount: str) -> Transaction:
            return Transaction(
                id="t",
                account_id=CC_ID,
                date=TODAY,
                amount=Decimal(amount),
                description="x",
            )

        self.assertEqual(card_invoice_signed_amount(tx("100"), purchase), Decimal("100"))
        self.assertEqual(card_invoice_signed_amount(tx("-30"), refund), Decimal("-30"))
        # A refund-classified row with a positive amount is unexpected → neutral.
        self.assertEqual(card_invoice_signed_amount(tx("30"), refund), Decimal("0"))
        self.assertEqual(card_invoice_signed_amount(tx("-500"), payment), Decimal("0"))


class CurrentMonthInvoiceSignTest(unittest.TestCase):
    """_current_month_invoice (calendar-month tier, no close_date)."""

    def setUp(self):
        self.engine = _make_engine()

    def _invoice(self, session):
        return planning_invoice_for_month(session, "2026-06", today=TODAY)

    def test_purchase_enters_open_invoice(self):
        with Session(self.engine) as session:
            _seed_credit_account(session)
            _add_tx(session, "buy-1", TODAY, "200.00", "Mercado", "Groceries")
            inv = self._invoice(session)
        self.assertEqual(inv["source"], "open_invoice")
        self.assertEqual(inv["amount"], 200.0)
        self.assertEqual(inv["transaction_count"], 1)
        self.assertIsNotNone(inv["cycle_start"])
        self.assertIsNotNone(inv["cycle_end"])

    def test_invoice_payment_does_not_inflate_open_invoice(self):
        with Session(self.engine) as session:
            _seed_credit_account(session)
            _add_tx(session, "buy-1", TODAY, "200.00", "Mercado", "Groceries")
            _add_tx(
                session,
                "pay-1",
                TODAY,
                "-1500.00",
                "Pagamento recebido",
                "Credit card payment",
            )
            inv = self._invoice(session)
        self.assertEqual(inv["source"], "open_invoice")
        self.assertEqual(inv["amount"], 200.0)

    def test_refund_reduces_open_invoice(self):
        with Session(self.engine) as session:
            _seed_credit_account(session)
            _add_tx(session, "buy-1", TODAY, "200.00", "Mercado", "Groceries")
            _add_tx(session, "canc-1", TODAY, "-50.00", "CANC PARCELA", "Shopping")
            inv = self._invoice(session)
        self.assertEqual(inv["source"], "open_invoice")
        self.assertEqual(inv["amount"], 150.0)
        self.assertEqual(inv["transaction_count"], 2)

    def test_open_invoice_total_never_negative(self):
        with Session(self.engine) as session:
            _seed_credit_account(session)
            _add_tx(session, "buy-1", TODAY, "40.00", "Mercado", "Groceries")
            _add_tx(session, "canc-1", TODAY, "-100.00", "Estorno compra", "Shopping")
            inv = self._invoice(session)
        self.assertEqual(inv["source"], "open_invoice")
        self.assertEqual(inv["amount"], 0.0)


class VigentePendingInvoiceSignTest(unittest.TestCase):
    """The vigente invoice includes only positive PENDING purchases."""

    def setUp(self):
        self.engine = _make_engine()

    def _seed(self, session):
        # close_date=2026-06-04, today=2026-06-12 → forming cycle
        # 2026-06-05..2026-07-04, due in the vigente month 2026-07.
        _seed_credit_account(
            session,
            credit_balance_close_date=datetime.date(2026, 6, 4),
        )

    def _invoice(self, session):
        return planning_invoice_for_month(session, "2026-07", today=TODAY)

    def test_same_convention_as_current_month(self):
        with Session(self.engine) as session:
            self._seed(session)
            _add_tx(session, "buy-1", datetime.date(2026, 6, 8), "300.00", "Loja", "Shopping")
            _add_tx(
                session, "canc-1", datetime.date(2026, 6, 10), "-100.00", "CANC PARCELA", "Shopping"
            )
            _add_tx(
                session,
                "pay-1",
                datetime.date(2026, 6, 9),
                "-2000.00",
                "Pagamento recebido",
                "Credit card payment",
            )
            inv = self._invoice(session)
        self.assertEqual(inv["source"], "pending_current_invoice")
        self.assertEqual(inv["amount"], 300.0)
        self.assertEqual(inv["transaction_count"], 1)

    def test_refunds_only_cycle_falls_through(self):
        # A cycle with no positive PENDING purchases produces a zero invoice.
        with Session(self.engine) as session:
            self._seed(session)
            _add_tx(
                session, "canc-1", datetime.date(2026, 6, 10), "-100.00", "CANC PARCELA", "Shopping"
            )
            inv = self._invoice(session)
        self.assertEqual(inv["source"], "pending_current_invoice")
        self.assertEqual(inv["amount"], 0.0)


class ScheduledInstallmentsSignTest(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def test_future_purchases_counted_and_refunds_ignored(self):
        with Session(self.engine) as session:
            _seed_credit_account(session)
            _add_tx(
                session, "parc-1", datetime.date(2026, 7, 15), "400.00", "Parcela 2/4", "Shopping"
            )
            _add_tx(
                session, "canc-1", datetime.date(2026, 7, 16), "-90.00", "CANC PARCELA", "Shopping"
            )
            result = scheduled_installments_for_month(session, "2026-07", today=TODAY)
        self.assertEqual(result["total"], 400.0)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["transactions"][0]["transaction_id"], "parc-1")


class SpendPickersSignTest(unittest.TestCase):
    """Gross spend pickers (snapshots/history/budget inputs) must treat
    refunds as neutral — never as positive spending."""

    def setUp(self):
        self.engine = _make_engine()

    def _seed_all(self, session):
        _seed_credit_account(session)
        _add_tx(session, "buy-1", TODAY, "200.00", "Mercado", "Groceries")
        _add_tx(session, "canc-1", TODAY, "-50.00", "CANC PARCELA", "Shopping")
        _add_tx(
            session,
            "pay-1",
            TODAY,
            "-1500.00",
            "Pagamento recebido",
            "Credit card payment",
        )

    def test_credit_card_spend_transactions_excludes_refunds_and_payments(self):
        with Session(self.engine) as session:
            self._seed_all(session)
            txs = credit_card_spend_transactions(session, TODAY, TODAY)
        self.assertEqual([tx.id for tx in txs], ["buy-1"])

    def test_discretionary_spend_excludes_refunds_and_payments(self):
        with Session(self.engine) as session:
            self._seed_all(session)
            txs = discretionary_spend_transactions(session, TODAY, TODAY)
        self.assertEqual([tx.id for tx in txs], ["buy-1"])


class InvoiceSummarySignTest(unittest.TestCase):
    """invoice_summary open totals: purchases add, refunds subtract,
    payments excluded, zero floor on the final total."""

    def setUp(self):
        self.engine = _make_engine()

    def test_refund_reduces_open_total(self):
        with Session(self.engine) as session:
            _seed_credit_account(session)
            _add_tx(session, "buy-1", TODAY, "200.00", "Mercado", "Groceries")
            _add_tx(session, "canc-1", TODAY, "-50.00", "CANC PARCELA", "Shopping")
            # Open totals only consider tx.date strictly after from_date.
            summary = invoice_summary(
                session,
                from_date=TODAY - datetime.timedelta(days=1),
                to_date=TODAY,
            )
        self.assertEqual(summary["invoice_open_total"], 150.0)
        self.assertEqual(summary["invoice_open_count"], 1)

    def test_open_total_floors_at_zero(self):
        with Session(self.engine) as session:
            _seed_credit_account(session)
            _add_tx(session, "buy-1", TODAY, "40.00", "Mercado", "Groceries")
            _add_tx(session, "canc-1", TODAY, "-100.00", "Estorno compra", "Shopping")
            summary = invoice_summary(
                session,
                from_date=TODAY - datetime.timedelta(days=1),
                to_date=TODAY,
            )
        self.assertEqual(summary["invoice_open_total"], 0.0)


if __name__ == "__main__":
    unittest.main()
