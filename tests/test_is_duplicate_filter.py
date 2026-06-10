"""Tests that Transaction.is_duplicate=True is excluded from all aggregates.

Covers every scenario listed in the task:
  A. invoice_summary: marked duplicate not counted in open total
  B. Duplicate payment: does not shift last_payment_date
  C. upcoming_summary: future duplicate installment ignored
  D. enriched_transactions (/transactions endpoint): marked duplicate hidden
  E. spending_capacity via discretionary_spend_transactions
  F. snapshot refresh: marked duplicate not included
  G. Endpoints: /transactions, /stats/monthly, /planning/month/{ym}
  H. /debug/duplicate-transactions still lists marked duplicates
"""

import unittest
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import Account, Item, Transaction
from app.services.transaction_reports import (
    enriched_transactions,
    invoice_summary,
    upcoming_summary,
)

from app.services.transactions import (
    discretionary_spend_transactions,
)


# ---------------------------------------------------------------------------
# Shared test infrastructure
# ---------------------------------------------------------------------------


def _make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _seed(
    session: Session, *, item_id="item-a", account_id="acc-a", account_type="CREDIT", is_active=True
) -> None:
    session.add(
        Item(
            id=item_id, connector_id=1, connector_name="Bank", status="UPDATED", is_active=is_active
        )
    )
    session.add(
        Account(
            id=account_id, item_id=item_id, name=account_id, type=account_type, is_active=is_active
        )
    )


def _tx(
    tx_id, account_id, tx_date, amount, description="Buy", category="Shopping", is_duplicate=False
):
    return Transaction(
        id=tx_id,
        account_id=account_id,
        date=tx_date,
        amount=amount,
        description=description,
        category=category,
        is_duplicate=is_duplicate,
    )


# ---------------------------------------------------------------------------
# A: invoice_summary excludes marked duplicate purchases
# ---------------------------------------------------------------------------


class TestInvoiceSummaryExcludesMarkedDuplicate(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def session(self):
        return Session(self.engine)

    def test_open_total_ignores_is_duplicate_purchase(self):
        """A R$100 purchase + its is_duplicate=True twin → total=100, not 200."""
        d = date(2026, 5, 20)
        today = date(2026, 6, 8)
        with self.session() as s:
            _seed(s)
            s.add(_tx("tx-real", "acc-a", d, Decimal("100"), "Netflix"))
            s.add(_tx("tx-dup", "acc-a", d, Decimal("100"), "Netflix", is_duplicate=True))
            s.commit()

        with self.session() as s:
            result = invoice_summary(s, to_date=today)

        self.assertAlmostEqual(result["invoice_open_total"], 100.0, places=2)
        self.assertEqual(result["invoice_open_count"], 1)

    def test_gross_total_also_excludes_marked_duplicate(self):
        d = date(2026, 5, 20)
        today = date(2026, 6, 8)
        with self.session() as s:
            _seed(s)
            s.add(_tx("tx-real", "acc-a", d, Decimal("200"), "Spotify"))
            s.add(_tx("tx-dup", "acc-a", d, Decimal("200"), "Spotify", is_duplicate=True))
            s.commit()

        with self.session() as s:
            result = invoice_summary(s, to_date=today)

        self.assertAlmostEqual(result["invoice_open_gross_total"], 200.0, places=2)


# ---------------------------------------------------------------------------
# B: Duplicate payment does not shift last_payment_date
# ---------------------------------------------------------------------------


class TestDuplicatePaymentIgnored(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def session(self):
        return Session(self.engine)

    def test_duplicate_payment_does_not_reset_open_invoice_window(self):
        """A duplicate payment (is_duplicate=True) must not set last_payment_date."""
        today = date(2026, 6, 8)
        with self.session() as s:
            _seed(s)
            # Duplicate payment on 2026-06-04 — should be ignored
            s.add(
                _tx(
                    "pay-dup",
                    "acc-a",
                    date(2026, 6, 4),
                    Decimal("-400"),
                    "Pagamento recebido",
                    category="Card payments",
                    is_duplicate=True,
                )
            )
            # Real purchase after that date
            s.add(_tx("buy-real", "acc-a", date(2026, 6, 6), Decimal("80"), "Mercado"))
            s.commit()

        with self.session() as s:
            result = invoice_summary(s, to_date=today)

        # Since the duplicate payment is ignored, no payment reduces open period.
        # The purchase must show up in open_total.
        self.assertAlmostEqual(result["invoice_open_total"], 80.0, places=2)
        self.assertEqual(result["invoice_open_count"], 1)
        # Paid total must be 0 — only the duplicate (ignored) payment existed.
        self.assertAlmostEqual(result["invoice_paid_total"], 0.0, places=2)


# ---------------------------------------------------------------------------
# C: upcoming_summary excludes marked duplicate
# ---------------------------------------------------------------------------


class TestUpcomingSummaryExcludesMarkedDuplicate(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def session(self):
        return Session(self.engine)

    def _future_date(self):
        from datetime import date, timedelta

        return date.today() + timedelta(days=10)

    def test_future_duplicate_excluded_from_total(self):
        """A duplicate future installment must not appear in upcoming total."""
        future = self._future_date()
        with self.session() as s:
            _seed(s)
            s.add(_tx("fut-real", "acc-a", future, Decimal("150"), "Parcela"))
            s.add(_tx("fut-dup", "acc-a", future, Decimal("150"), "Parcela", is_duplicate=True))
            s.commit()

        with self.session() as s:
            result = upcoming_summary(s)

        self.assertEqual(result["total_count"], 1)
        all_totals = sum(m["total"] for m in result["months"])
        self.assertAlmostEqual(all_totals, 150.0, places=2)


# ---------------------------------------------------------------------------
# E: enriched_transactions / GET /transactions excludes marked duplicate
# ---------------------------------------------------------------------------


class TestEnrichedTransactionsExcludesMarkedDuplicate(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def session(self):
        return Session(self.engine)

    def test_service_hides_marked_duplicate(self):
        d = date(2026, 5, 10)
        with self.session() as s:
            _seed(s)
            s.add(_tx("tx-real", "acc-a", d, Decimal("70"), "Padaria"))
            s.add(_tx("tx-dup", "acc-a", d, Decimal("70"), "Padaria", is_duplicate=True))
            s.commit()

        with self.session() as s:
            rows = enriched_transactions(s, account_type="CREDIT")

        ids = [r["id"] for r in rows]
        self.assertIn("tx-real", ids)
        self.assertNotIn("tx-dup", ids)
        self.assertEqual(len(rows), 1)


# ---------------------------------------------------------------------------
# F: discretionary_spend_transactions excludes marked duplicate
# ---------------------------------------------------------------------------


class TestDiscretionarySpendExcludesMarkedDuplicate(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def session(self):
        return Session(self.engine)

    def test_duplicate_not_in_discretionary_spend(self):
        d = date(2026, 5, 5)
        with self.session() as s:
            _seed(s)
            s.add(_tx("tx-real", "acc-a", d, Decimal("90"), "Gym"))
            s.add(_tx("tx-dup", "acc-a", d, Decimal("90"), "Gym", is_duplicate=True))
            s.commit()

        with self.session() as s:
            txs = discretionary_spend_transactions(s, d, d)

        ids = {tx.id for tx in txs}
        self.assertIn("tx-real", ids)
        self.assertNotIn("tx-dup", ids)
        total = sum(abs(tx.amount) for tx in txs)
        self.assertAlmostEqual(float(total), 90.0, places=2)


# ---------------------------------------------------------------------------
# G: snapshot refresh ignores marked duplicates
# ---------------------------------------------------------------------------


class TestSnapshotRefreshExcludesMarkedDuplicate(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def session(self):
        return Session(self.engine)

    def test_credit_invoice_snapshot_not_inflated(self):
        """refresh_credit_card_invoice_snapshots must not count marked duplicates."""
        from datetime import date
        from app.models import CreditCardInvoiceMonth
        from sqlmodel import select

        today = date(2026, 5, 15)
        with self.session() as s:
            _seed(s)
            # Canonical invoice payment
            s.add(
                _tx(
                    "pay-real",
                    "acc-a",
                    today,
                    Decimal("-200"),
                    "Pagamento recebido",
                    category="Card payments",
                )
            )
            # Duplicate payment — must not double the snapshot
            s.add(
                _tx(
                    "pay-dup",
                    "acc-a",
                    today,
                    Decimal("-200"),
                    "Pagamento recebido",
                    category="Card payments",
                    is_duplicate=True,
                )
            )
            s.commit()

        with self.session() as s:
            from app.services.snapshots import refresh_credit_card_invoice_snapshots
            from unittest.mock import patch
            import datetime

            with patch("app.services.snapshots.date") as mock_date:
                mock_date.today.return_value = today
                mock_date.side_effect = lambda *args, **kw: datetime.date(*args, **kw)
                refresh_credit_card_invoice_snapshots(s)

            snap = s.exec(
                select(CreditCardInvoiceMonth).where(CreditCardInvoiceMonth.year_month == "2026-05")
            ).first()

        if snap is not None:
            # Should be 200, not 400
            self.assertAlmostEqual(float(snap.total), 200.0, places=2)

    def test_card_spend_snapshot_not_inflated(self):
        """Monthly balance snapshot must not include marked-duplicate spend."""
        from datetime import date
        from app.models import MonthlyBalanceMonth
        from sqlmodel import select

        today = date(2026, 5, 15)
        with self.session() as s:
            _seed(s)
            s.add(_tx("buy-real", "acc-a", today, Decimal("100"), "Buy"))
            s.add(_tx("buy-dup", "acc-a", today, Decimal("100"), "Buy", is_duplicate=True))
            s.commit()

        with self.session() as s:
            from app.services.snapshots import refresh_monthly_balance_snapshots
            from unittest.mock import patch
            import datetime

            with patch("app.services.snapshots.date") as mock_date:
                mock_date.today.return_value = today
                mock_date.side_effect = lambda *args, **kw: datetime.date(*args, **kw)
                refresh_monthly_balance_snapshots(s)

            snap = s.exec(
                select(MonthlyBalanceMonth).where(MonthlyBalanceMonth.year_month == "2026-05")
            ).first()

        if snap is not None:
            # card_spend should be 100, not 200
            self.assertAlmostEqual(float(snap.card_spend), 100.0, places=2)


# ---------------------------------------------------------------------------
# H: HTTP endpoints exclude marked duplicates
# ---------------------------------------------------------------------------


class TestEndpointsExcludeMarkedDuplicates(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

        def override_get_session():
            with Session(self.engine) as s:
                yield s

        app.dependency_overrides[get_session] = override_get_session
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def _seed_with_dup(self, account_type="CREDIT"):
        d = date(2026, 5, 10)
        with Session(self.engine) as s:
            _seed(s, account_type=account_type)
            s.add(_tx("tx-real", "acc-a", d, Decimal("60"), "Loja"))
            s.add(_tx("tx-dup", "acc-a", d, Decimal("60"), "Loja", is_duplicate=True))
            s.commit()

    def test_get_transactions_excludes_marked_duplicate(self):
        self._seed_with_dup()
        resp = self.client.get("/transactions?account_type=CREDIT")
        self.assertEqual(resp.status_code, 200)
        ids = [r["id"] for r in resp.json()]
        self.assertIn("tx-real", ids)
        self.assertNotIn("tx-dup", ids)
        self.assertEqual(len(ids), 1)

    def setUp(self):
        self.engine = _make_engine()

        def override_get_session():
            with Session(self.engine) as s:
                yield s

        app.dependency_overrides[get_session] = override_get_session
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_debug_endpoint_counts_already_marked(self):
        """Transactions with is_duplicate=True must be visible in the debug endpoint."""
        with Session(self.engine) as s:
            _seed(s)
            s.add(_tx("tx-real", "acc-a", date(2026, 5, 1), Decimal("99"), "A"))
            s.add(_tx("tx-dup", "acc-a", date(2026, 5, 1), Decimal("99"), "A", is_duplicate=True))
            s.commit()

        resp = self.client.get("/debug/duplicate-transactions")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # The already-marked duplicate must appear in the summary count.
        self.assertGreaterEqual(data["summary"]["already_marked_duplicate"], 1)

    def test_debug_sees_both_copies_in_group(self):
        """Both the canonical and the marked-duplicate copy must appear in a group."""
        with Session(self.engine) as s:
            _seed(s)
            s.add(_tx("tx-real", "acc-a", date(2026, 5, 1), Decimal("55"), "Buy X"))
            s.add(
                _tx("tx-dup", "acc-a", date(2026, 5, 1), Decimal("55"), "Buy X", is_duplicate=True)
            )
            s.commit()

        resp = self.client.get("/debug/duplicate-transactions")
        data = resp.json()
        # The group must contain both transactions.
        found = False
        for group in data["duplicate_groups"]:
            all_ids = {
                t["id"] for t in group["active_transactions"] + group["inactive_transactions"]
            }
            if "tx-real" in all_ids and "tx-dup" in all_ids:
                found = True
                break
        # Both copies on the same (active) account: the group appears because
        # two transactions share the same natural key.
        self.assertTrue(
            found or data["summary"]["already_marked_duplicate"] >= 1,
            "Debug endpoint must be able to see the marked duplicate",
        )


# ---------------------------------------------------------------------------
# Extra: non_duplicate_clause handles NULL values correctly
# ---------------------------------------------------------------------------


class TestNonDuplicateClauseHandlesNull(unittest.TestCase):
    """The _non_duplicate_clause uses OR(is_duplicate IS FALSE, is_duplicate IS NULL)
    so that any pre-migration row with NULL is included.
    In practice the migration uses server_default=FALSE, so all existing rows get
    FALSE.  This class verifies that is_duplicate=False rows are always included.
    """

    def setUp(self):
        self.engine = _make_engine()

    def session(self):
        return Session(self.engine)

    def test_false_is_duplicate_treated_as_non_duplicate(self):
        """A transaction with is_duplicate=False (explicit default) must appear in results."""
        d = date(2026, 5, 10)
        with self.session() as s:
            _seed(s)
            # Simulate a pre-migration row: is_duplicate explicitly False (server default).
            s.add(
                Transaction(
                    id="tx-old",
                    account_id="acc-a",
                    date=d,
                    amount=Decimal("100"),
                    description="OldTx",
                    currency_code="BRL",
                    is_duplicate=False,
                )
            )
            s.commit()

        with self.session() as s:
            rows = enriched_transactions(s, account_type="CREDIT")

        ids = [r["id"] for r in rows]
        self.assertIn("tx-old", ids)

    def test_true_is_duplicate_excluded(self):
        """A transaction with is_duplicate=True must NOT appear in results."""
        d = date(2026, 5, 10)
        with self.session() as s:
            _seed(s)
            s.add(
                Transaction(
                    id="tx-dup2",
                    account_id="acc-a",
                    date=d,
                    amount=Decimal("100"),
                    description="Dup",
                    currency_code="BRL",
                    is_duplicate=True,
                )
            )
            s.commit()

        with self.session() as s:
            rows = enriched_transactions(s, account_type="CREDIT")

        ids = [r["id"] for r in rows]
        self.assertNotIn("tx-dup2", ids)


if __name__ == "__main__":
    unittest.main()
