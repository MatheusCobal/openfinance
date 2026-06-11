"""Tests for duplicate transaction detection, filtering, and diagnostic endpoint.

Covers:
  - compute_dedupe_key stability
  - invoice_summary filters payments from inactive accounts
  - invoice_summary open_total excludes inactive account transactions
  - GET /debug/duplicate-transactions returns correct counts and groups
  - account_ids_by_type(active_only=True) excludes inactive accounts
  - Inactive-account transactions are excluded from all main report functions
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
from app.services.sync import compute_dedupe_key
from app.services.transaction_reports import invoice_summary
from app.services.transactions import account_ids_by_type, credit_card_spend_transactions



def _make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _seed_item(session: Session, item_id: str, is_active: bool = True) -> Item:
    item = Item(
        id=item_id,
        connector_id=1,
        connector_name="TestBank",
        status="UPDATED",
        is_active=is_active,
    )
    session.add(item)
    return item


def _seed_account(
    session: Session,
    account_id: str,
    item_id: str,
    account_type: str = "CREDIT",
    is_active: bool = True,
) -> Account:
    account = Account(
        id=account_id,
        item_id=item_id,
        name=account_id,
        type=account_type,
        is_active=is_active,
    )
    session.add(account)
    return account


def _seed_tx(
    session: Session,
    tx_id: str,
    account_id: str,
    tx_date: date,
    amount: Decimal,
    description: str,
    category: str = "Shopping",
    installment_number: int = None,
    total_installments: int = None,
) -> Transaction:
    tx = Transaction(
        id=tx_id,
        account_id=account_id,
        date=tx_date,
        amount=amount,
        description=description,
        category=category,
        installment_number=installment_number,
        total_installments=total_installments,
    )
    session.add(tx)
    return tx


# ---------------------------------------------------------------------------
# Tests: compute_dedupe_key
# ---------------------------------------------------------------------------


class TestComputeDedupeKey(unittest.TestCase):
    def test_same_inputs_produce_same_key(self):
        k1 = compute_dedupe_key("CREDIT", "Netflix", date(2026, 5, 1), Decimal("49.90"), None, None)
        k2 = compute_dedupe_key("CREDIT", "Netflix", date(2026, 5, 1), Decimal("49.90"), None, None)
        self.assertEqual(k1, k2)

    def test_different_description_produces_different_key(self):
        k1 = compute_dedupe_key("CREDIT", "Netflix", date(2026, 5, 1), Decimal("49.90"), None, None)
        k2 = compute_dedupe_key("CREDIT", "Spotify", date(2026, 5, 1), Decimal("49.90"), None, None)
        self.assertNotEqual(k1, k2)

    def test_different_date_produces_different_key(self):
        k1 = compute_dedupe_key("CREDIT", "Netflix", date(2026, 5, 1), Decimal("49.90"), None, None)
        k2 = compute_dedupe_key("CREDIT", "Netflix", date(2026, 5, 2), Decimal("49.90"), None, None)
        self.assertNotEqual(k1, k2)

    def test_different_amount_produces_different_key(self):
        k1 = compute_dedupe_key("CREDIT", "Netflix", date(2026, 5, 1), Decimal("49.90"), None, None)
        k2 = compute_dedupe_key("CREDIT", "Netflix", date(2026, 5, 1), Decimal("50.00"), None, None)
        self.assertNotEqual(k1, k2)

    def test_amount_sign_ignored(self):
        """Both positive and negative amounts with the same |value| map to the same key."""
        k1 = compute_dedupe_key("CREDIT", "Netflix", date(2026, 5, 1), Decimal("49.90"), None, None)
        k2 = compute_dedupe_key(
            "CREDIT", "Netflix", date(2026, 5, 1), Decimal("-49.90"), None, None
        )
        self.assertEqual(k1, k2)

    def test_installment_fields_affect_key(self):
        k1 = compute_dedupe_key("CREDIT", "TV 4K", date(2026, 5, 1), Decimal("100"), 1, 12)
        k2 = compute_dedupe_key("CREDIT", "TV 4K", date(2026, 5, 1), Decimal("100"), 2, 12)
        self.assertNotEqual(k1, k2)

    def test_account_type_affects_key(self):
        k1 = compute_dedupe_key("CREDIT", "PIX", date(2026, 5, 1), Decimal("100"), None, None)
        k2 = compute_dedupe_key("BANK", "PIX", date(2026, 5, 1), Decimal("100"), None, None)
        self.assertNotEqual(k1, k2)

    def test_key_length_is_32(self):
        k = compute_dedupe_key("CREDIT", "Test", date(2026, 5, 1), Decimal("10"), None, None)
        self.assertEqual(len(k), 32)

    def test_description_normalised_before_hashing(self):
        """Descriptions that differ only by case/accents should map to the same key."""
        k1 = compute_dedupe_key(
            "CREDIT", "NETFLIX BR", date(2026, 5, 1), Decimal("49.90"), None, None
        )
        k2 = compute_dedupe_key(
            "CREDIT", "netflix br", date(2026, 5, 1), Decimal("49.90"), None, None
        )
        self.assertEqual(k1, k2)


# ---------------------------------------------------------------------------
# Tests: account_ids_by_type active filtering
# ---------------------------------------------------------------------------


class TestAccountIdsByTypeFiltering(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def _session(self):
        return Session(self.engine)

    def test_active_only_excludes_inactive_accounts(self):
        with self._session() as session:
            _seed_item(session, "item-a", is_active=True)
            _seed_account(session, "acc-active", "item-a", is_active=True)
            _seed_account(session, "acc-inactive", "item-a", is_active=False)
            session.commit()

        with self._session() as session:
            ids = account_ids_by_type(session, {"CREDIT"}, active_only=True)

        self.assertIn("acc-active", ids)
        self.assertNotIn("acc-inactive", ids)

    def test_active_only_excludes_accounts_from_inactive_items(self):
        with self._session() as session:
            _seed_item(session, "item-old", is_active=False)
            _seed_account(
                session, "acc-old", "item-old", is_active=True
            )  # account says active but item is not
            _seed_item(session, "item-new", is_active=True)
            _seed_account(session, "acc-new", "item-new", is_active=True)
            session.commit()

        with self._session() as session:
            ids = account_ids_by_type(session, {"CREDIT"}, active_only=True)

        self.assertNotIn("acc-old", ids)
        self.assertIn("acc-new", ids)

    def test_active_only_false_includes_inactive(self):
        with self._session() as session:
            _seed_item(session, "item-x", is_active=False)
            _seed_account(session, "acc-x", "item-x", is_active=False)
            session.commit()

        with self._session() as session:
            ids = account_ids_by_type(session, {"CREDIT"}, active_only=False)

        self.assertIn("acc-x", ids)


# ---------------------------------------------------------------------------
# Tests: invoice_summary active account filtering
# ---------------------------------------------------------------------------


class TestInvoiceSummaryActiveFiltering(unittest.TestCase):
    """invoice_summary must exclude transactions from inactive accounts."""

    def setUp(self):
        self.engine = _make_engine()

    def _session(self):
        return Session(self.engine)

    def test_open_total_excludes_inactive_account_transactions(self):
        """Purchases on an inactive (old) account must NOT appear in invoice_open_total."""
        today = date(2026, 6, 8)
        with self._session() as session:
            # Old item + account (inactive after re-auth)
            _seed_item(session, "item-old", is_active=False)
            _seed_account(session, "acc-old", "item-old", is_active=False)
            # New item + account (active)
            _seed_item(session, "item-new", is_active=True)
            _seed_account(session, "acc-new", "item-new", is_active=True)

            # Same purchase duplicated on both accounts
            _seed_tx(session, "tx-old-1", "acc-old", date(2026, 5, 20), Decimal("200"), "Compra A")
            _seed_tx(session, "tx-new-1", "acc-new", date(2026, 5, 20), Decimal("200"), "Compra A")
            session.commit()

        with self._session() as session:
            result = invoice_summary(session, to_date=today)

        # Only the active account transaction should be counted.
        self.assertAlmostEqual(result["invoice_open_total"], 200.0, places=2)

    def test_open_total_not_doubled_when_old_account_deactivated(self):
        """After re-auth: with inactive old account, total should be X, not 2X."""
        today = date(2026, 6, 8)
        with self._session() as session:
            _seed_item(session, "item-old", is_active=False)
            _seed_account(session, "acc-old", "item-old", is_active=False)
            _seed_item(session, "item-new", is_active=True)
            _seed_account(session, "acc-new", "item-new", is_active=True)

            for i in range(3):
                _seed_tx(
                    session,
                    f"tx-old-{i}",
                    "acc-old",
                    date(2026, 5, 10 + i),
                    Decimal("100"),
                    f"Compra {i}",
                )
                _seed_tx(
                    session,
                    f"tx-new-{i}",
                    "acc-new",
                    date(2026, 5, 10 + i),
                    Decimal("100"),
                    f"Compra {i}",
                )
            session.commit()

        with self._session() as session:
            result = invoice_summary(session, to_date=today)

        # Should be 300 (3 × 100) not 600 (doubled).
        self.assertAlmostEqual(result["invoice_open_total"], 300.0, places=2)

    def test_last_payment_date_unaffected_by_inactive_account_payments(self):
        """Payments on an inactive account must not influence last_payment_date."""
        today = date(2026, 6, 8)
        with self._session() as session:
            _seed_item(session, "item-old", is_active=False)
            _seed_account(session, "acc-old", "item-old", is_active=False)
            _seed_item(session, "item-new", is_active=True)
            _seed_account(session, "acc-new", "item-new", is_active=True)

            # Payment on old inactive account — should be ignored
            _seed_tx(
                session,
                "pay-old",
                "acc-old",
                date(2026, 6, 5),
                Decimal("-500"),
                "Pagamento recebido",
                category="Card payments",
            )
            # Purchase on new active account (should appear in open_total)
            _seed_tx(session, "buy-new", "acc-new", date(2026, 6, 6), Decimal("150"), "Mercado")
            session.commit()

        with self._session() as session:
            result = invoice_summary(session, to_date=today)

        # Payment on inactive account must NOT reset the open-invoice period.
        # The purchase on the active account (buy-new, R$150) must appear.
        self.assertEqual(result["invoice_open_count"], 1)
        self.assertAlmostEqual(result["invoice_open_total"], 150.0, places=2)

    def test_active_account_payments_still_detected(self):
        """Payments on active accounts must still be counted normally."""
        today = date(2026, 6, 8)
        with self._session() as session:
            _seed_item(session, "item-new", is_active=True)
            _seed_account(session, "acc-new", "item-new", is_active=True)

            _seed_tx(
                session,
                "pay-new",
                "acc-new",
                date(2026, 6, 4),
                Decimal("-400"),
                "Pagamento recebido",
                category="Card payments",
            )
            _seed_tx(session, "buy-new", "acc-new", date(2026, 6, 6), Decimal("80"), "Padaria")
            session.commit()

        with self._session() as session:
            result = invoice_summary(session, to_date=today)

        # Payment on active account should set last_payment_date and reduce open period.
        self.assertGreater(result["invoice_paid_total"], 0.0)


# ---------------------------------------------------------------------------
# Tests: credit_card_spend_transactions active filtering
# ---------------------------------------------------------------------------


class TestCreditCardSpendActiveFiltering(unittest.TestCase):
    """credit_card_spend_transactions must only return transactions from active accounts."""

    def setUp(self):
        self.engine = _make_engine()

    def _session(self):
        return Session(self.engine)

    def test_excludes_inactive_account_spend(self):
        today = date(2026, 6, 8)
        with self._session() as session:
            _seed_item(session, "item-old", is_active=False)
            _seed_account(session, "acc-old", "item-old", is_active=False)
            _seed_item(session, "item-new", is_active=True)
            _seed_account(session, "acc-new", "item-new", is_active=True)

            _seed_tx(session, "tx-old", "acc-old", today, Decimal("999"), "Old spend")
            _seed_tx(session, "tx-new", "acc-new", today, Decimal("50"), "New spend")
            session.commit()

        with self._session() as session:
            txs = credit_card_spend_transactions(session, today, today)

        ids = {tx.id for tx in txs}
        self.assertIn("tx-new", ids)
        self.assertNotIn("tx-old", ids)


# ---------------------------------------------------------------------------
# Tests: GET /debug/duplicate-transactions endpoint
# ---------------------------------------------------------------------------


class TestDebugDuplicateTransactionsEndpoint(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_get_session
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def _seed_reauth_scenario(self) -> None:
        """Seed a realistic re-auth scenario: old inactive + new active account with duplicates."""
        with Session(self.engine) as session:
            _seed_item(session, "item-old", is_active=False)
            _seed_account(session, "acc-old", "item-old", is_active=False)
            _seed_item(session, "item-new", is_active=True)
            _seed_account(session, "acc-new", "item-new", is_active=True)

            # Duplicate purchase (same natural key, different tx IDs)
            _seed_tx(session, "tx-old-1", "acc-old", date(2026, 5, 10), Decimal("200"), "Netflix")
            _seed_tx(session, "tx-new-1", "acc-new", date(2026, 5, 10), Decimal("200"), "Netflix")

            # Another duplicate
            _seed_tx(session, "tx-old-2", "acc-old", date(2026, 5, 15), Decimal("50"), "Spotify")
            _seed_tx(session, "tx-new-2", "acc-new", date(2026, 5, 15), Decimal("50"), "Spotify")

            # Unique transaction on new account only (no duplicate)
            _seed_tx(session, "tx-new-only", "acc-new", date(2026, 6, 1), Decimal("30"), "Padaria")
            session.commit()

    def test_endpoint_returns_200(self):
        resp = self.client.get("/debug/duplicate-transactions")
        self.assertEqual(resp.status_code, 200)

    def test_empty_db_returns_zero_duplicates(self):
        resp = self.client.get("/debug/duplicate-transactions")
        data = resp.json()
        self.assertEqual(data["summary"]["duplicate_groups_found"], 0)
        self.assertEqual(data["summary"]["inactive_duplicates_found"], 0)

    def test_detects_duplicate_groups(self):
        self._seed_reauth_scenario()
        resp = self.client.get("/debug/duplicate-transactions")
        data = resp.json()
        # Should detect 2 duplicate groups (Netflix + Spotify)
        self.assertEqual(data["summary"]["duplicate_groups_found"], 2)

    def test_inactive_duplicates_count_correct(self):
        self._seed_reauth_scenario()
        resp = self.client.get("/debug/duplicate-transactions")
        data = resp.json()
        # 2 transactions on inactive account (Netflix + Spotify)
        self.assertEqual(data["summary"]["inactive_duplicates_found"], 2)

    def test_inactive_duplicate_amount_correct(self):
        self._seed_reauth_scenario()
        resp = self.client.get("/debug/duplicate-transactions")
        data = resp.json()
        # Netflix 200 + Spotify 50 = 250
        self.assertAlmostEqual(data["summary"]["inactive_duplicate_amount"], 250.0, places=2)

    def test_duplicate_group_has_active_and_inactive_transactions(self):
        self._seed_reauth_scenario()
        resp = self.client.get("/debug/duplicate-transactions")
        data = resp.json()
        groups = data["duplicate_groups"]
        self.assertTrue(len(groups) >= 1)
        for group in groups:
            self.assertEqual(group["active_count"], 1)
            self.assertEqual(group["inactive_count"], 1)

    def test_unique_transactions_not_in_groups(self):
        """Transactions with no duplicates must not appear in duplicate_groups."""
        self._seed_reauth_scenario()
        resp = self.client.get("/debug/duplicate-transactions")
        data = resp.json()
        all_group_ids = {
            tx["id"]
            for group in data["duplicate_groups"]
            for tx in group["active_transactions"] + group["inactive_transactions"]
        }
        self.assertNotIn("tx-new-only", all_group_ids)

    def test_inactive_accounts_section_contains_old_account(self):
        self._seed_reauth_scenario()
        resp = self.client.get("/debug/duplicate-transactions")
        data = resp.json()
        inactive_ids = {a["account_id"] for a in data["inactive_accounts_with_transactions"]}
        self.assertIn("acc-old", inactive_ids)

    def test_no_duplicates_when_only_active_accounts(self):
        """If only active accounts exist, no duplicates should be found."""
        with Session(self.engine) as session:
            _seed_item(session, "item-only", is_active=True)
            _seed_account(session, "acc-only", "item-only", is_active=True)
            _seed_tx(session, "tx-1", "acc-only", date(2026, 6, 1), Decimal("100"), "Buy A")
            _seed_tx(session, "tx-2", "acc-only", date(2026, 6, 2), Decimal("100"), "Buy A")
            session.commit()

        resp = self.client.get("/debug/duplicate-transactions")
        data = resp.json()
        # Two transactions on active accounts with the same description/amount/date?
        # They WOULD appear as a group (same natural key, different dates → 0 groups).
        # But tx-1 and tx-2 have DIFFERENT dates (6-01 vs 6-02), so no group.
        self.assertEqual(data["summary"]["inactive_duplicates_found"], 0)

    def test_already_marked_count_in_summary(self):
        """Transactions already marked is_duplicate=True should appear in summary."""
        with Session(self.engine) as session:
            _seed_item(session, "item-z", is_active=True)
            _seed_account(session, "acc-z", "item-z", is_active=True)
            tx = Transaction(
                id="tx-marked",
                account_id="acc-z",
                date=date(2026, 5, 1),
                amount=Decimal("99"),
                description="Old",
                is_duplicate=True,
            )
            session.add(tx)
            session.commit()

        resp = self.client.get("/debug/duplicate-transactions")
        data = resp.json()
        self.assertEqual(data["summary"]["already_marked_duplicate"], 1)


# ---------------------------------------------------------------------------
# Tests: monthly_stats_summary excludes inactive accounts
# ---------------------------------------------------------------------------


class TestMonthlyStatsSummaryActiveFiltering(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def _session(self):
        return Session(self.engine)

if __name__ == "__main__":
    unittest.main()
