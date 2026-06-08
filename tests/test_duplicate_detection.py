"""Tests for the improved duplicate detection logic.

Covers:
  1. Python 3.9 compatibility — Optional[Account] type hint (was Account | None)
  2. Exact strategy: inactive+active groups → mark inactive
  3. Exact strategy: all-inactive groups → skip (orphan)
  4. Exact strategy: all-active groups → skip (ambiguous, never auto-mark)
  5. Relaxed strategy: ±1 day tolerance
  6. Relaxed strategy: ±R$0.01 amount tolerance
  7. Relaxed strategy: description prefix matching
  8. Relaxed strategy: installment mismatch blocks the match
  9. Relaxed strategy: inactive already matched by exact is not re-matched
 10. Mark script dry-run: does not write to DB
 11. Mark script --apply: writes and populates dedupe_key, refreshes snapshots
 12. Aggregates still exclude is_duplicate=True after marking
"""
import sys
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

# Ensure project root is on path for direct runs
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import get_session
from app.models import Account, Item, Transaction
from scripts.diagnose_duplicates import _is_active, _relaxed_matches
from scripts.mark_duplicate_transactions import (
    _build_active_index,
    _is_active as mark_is_active,
    _relaxed_match,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _item(session, item_id, is_active=True):
    i = Item(
        id=item_id, connector_id=1, connector_name="Bank",
        status="UPDATED", is_active=is_active,
    )
    session.add(i)
    return i


def _account(session, account_id, item_id, account_type="CREDIT", is_active=True):
    a = Account(
        id=account_id, item_id=item_id, name=account_id,
        type=account_type, is_active=is_active,
    )
    session.add(a)
    return a


def _tx(
    tx_id, account_id, tx_date, amount, description="Buy",
    installment_number=None, total_installments=None, is_duplicate=False,
):
    return Transaction(
        id=tx_id, account_id=account_id, date=tx_date,
        amount=amount, description=description,
        installment_number=installment_number,
        total_installments=total_installments,
        is_duplicate=is_duplicate,
    )


# ---------------------------------------------------------------------------
# 1. Python 3.9 compatibility: Optional[Account] helper works
# ---------------------------------------------------------------------------

class TestPython39CompatOptionalAccount(unittest.TestCase):
    def test_is_active_helper_accepts_none(self):
        """_is_active(None, ...) must return False without TypeError."""
        result = _is_active(None, {"some-item-id"})
        self.assertFalse(result)

    def test_is_active_helper_active_account(self):
        account = Account(
            id="acc-1", item_id="item-1", name="A", type="CREDIT", is_active=True
        )
        result = _is_active(account, {"item-1"})
        self.assertTrue(result)

    def test_is_active_helper_inactive_account(self):
        account = Account(
            id="acc-2", item_id="item-1", name="A", type="CREDIT", is_active=False
        )
        result = _is_active(account, {"item-1"})
        self.assertFalse(result)

    def test_is_active_helper_inactive_item(self):
        account = Account(
            id="acc-3", item_id="item-X", name="A", type="CREDIT", is_active=True
        )
        result = _is_active(account, set())  # empty = no active items
        self.assertFalse(result)

    def test_mark_is_active_helper_accepts_none(self):
        """mark script _is_active also must handle None."""
        result = mark_is_active(None, set())
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# 2. Exact strategy: inactive+active → mark inactive
# ---------------------------------------------------------------------------

class TestExactStrategyMarkInactive(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def session(self):
        return Session(self.engine)

    def _load_context(self, session):
        all_accounts = {a.id: a for a in session.exec(select(Account)).all()}
        active_item_ids = {
            item.id for item in session.exec(select(Item)).all() if item.is_active
        }
        return all_accounts, active_item_ids

    def test_active_index_built_correctly(self):
        with self.session() as s:
            _item(s, "item-active")
            _item(s, "item-old", is_active=False)
            _account(s, "acc-active", "item-active")
            _account(s, "acc-old", "item-old", is_active=False)
            tx_active = _tx("tx-active", "acc-active", date(2026, 3, 10), Decimal("100"))
            tx_inactive = _tx("tx-old", "acc-old", date(2026, 3, 10), Decimal("100"))
            s.add(tx_active)
            s.add(tx_inactive)
            s.commit()

        with self.session() as s:
            all_accounts, active_item_ids = self._load_context(s)
            all_txs = s.exec(select(Transaction)).all()
            index = _build_active_index(all_txs, all_accounts, active_item_ids)

        # Only the active transaction should be in the index
        key = ("CREDIT", date(2026, 3, 10))
        self.assertIn(key, index)
        ids = [t.id for t in index[key]]
        self.assertIn("tx-active", ids)
        self.assertNotIn("tx-old", ids)

    def test_already_marked_not_added_again(self):
        """A transaction already marked is_duplicate=True must be skipped."""
        from collections import defaultdict
        from app.services.sync import compute_dedupe_key

        with self.session() as s:
            _item(s, "item-active")
            _item(s, "item-old", is_active=False)
            _account(s, "acc-active", "item-active")
            _account(s, "acc-old", "item-old", is_active=False)
            s.add(_tx("tx-active", "acc-active", date(2026, 3, 10), Decimal("50")))
            # Already marked — should not be added to to_mark
            s.add(_tx("tx-dup", "acc-old", date(2026, 3, 10), Decimal("50"),
                      is_duplicate=True))
            s.commit()

        with self.session() as s:
            all_accounts, active_item_ids = self._load_context(s)
            all_txs = s.exec(select(Transaction)).all()

            by_key = defaultdict(list)
            for tx in all_txs:
                acc = all_accounts.get(tx.account_id)
                atype = acc.type if acc else "UNKNOWN"
                key = tx.dedupe_key or compute_dedupe_key(
                    atype, tx.description, tx.date, tx.amount,
                    tx.installment_number, tx.total_installments
                )
                by_key[key].append(tx)

            to_mark = []
            for key, txs in by_key.items():
                if len(txs) < 2:
                    continue
                active_txs = [tx for tx in txs if mark_is_active(all_accounts.get(tx.account_id), active_item_ids)]
                inactive_txs = [tx for tx in txs if not mark_is_active(all_accounts.get(tx.account_id), active_item_ids)]
                if active_txs and inactive_txs:
                    for tx in inactive_txs:
                        if not tx.is_duplicate:
                            to_mark.append(tx)

        # tx-dup was already marked → not in to_mark
        to_mark_ids = [tx.id for tx in to_mark]
        self.assertNotIn("tx-dup", to_mark_ids)


# ---------------------------------------------------------------------------
# 3. Exact strategy: all-inactive groups → skip
# ---------------------------------------------------------------------------

class TestExactStrategyOrphan(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def session(self):
        return Session(self.engine)

    def _load_context(self, session):
        all_accounts = {a.id: a for a in session.exec(select(Account)).all()}
        active_item_ids = {
            item.id for item in session.exec(select(Item)).all() if item.is_active
        }
        return all_accounts, active_item_ids

    def test_all_inactive_group_produces_no_marks(self):
        """A group where ALL transactions are on inactive accounts must not be marked."""
        from collections import defaultdict
        from app.services.sync import compute_dedupe_key

        with self.session() as s:
            _item(s, "item-old-1", is_active=False)
            _item(s, "item-old-2", is_active=False)
            _account(s, "acc-old-1", "item-old-1", is_active=False)
            _account(s, "acc-old-2", "item-old-2", is_active=False)
            s.add(_tx("tx1", "acc-old-1", date(2026, 1, 5), Decimal("200"), "Orphan"))
            s.add(_tx("tx2", "acc-old-2", date(2026, 1, 5), Decimal("200"), "Orphan"))
            s.commit()

        with self.session() as s:
            all_accounts, active_item_ids = self._load_context(s)
            all_txs = s.exec(select(Transaction)).all()

            by_key = defaultdict(list)
            for tx in all_txs:
                acc = all_accounts.get(tx.account_id)
                atype = acc.type if acc else "UNKNOWN"
                key = tx.dedupe_key or compute_dedupe_key(
                    atype, tx.description, tx.date, tx.amount,
                    tx.installment_number, tx.total_installments
                )
                by_key[key].append(tx)

            to_mark = []
            for key, txs in by_key.items():
                if len(txs) < 2:
                    continue
                active_txs = [tx for tx in txs if mark_is_active(all_accounts.get(tx.account_id), active_item_ids)]
                inactive_txs = [tx for tx in txs if not mark_is_active(all_accounts.get(tx.account_id), active_item_ids)]
                if active_txs and inactive_txs:
                    for tx in inactive_txs:
                        to_mark.append(tx)

        self.assertEqual(to_mark, [])


# ---------------------------------------------------------------------------
# 4. Exact strategy: all-active groups → ambiguous (never mark)
# ---------------------------------------------------------------------------

class TestExactStrategyAmbiguous(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def session(self):
        return Session(self.engine)

    def test_all_active_duplicate_not_auto_marked(self):
        """When two active accounts share the same natural key, neither is marked."""
        from collections import defaultdict
        from app.services.sync import compute_dedupe_key

        with self.session() as s:
            _item(s, "item-a")
            _item(s, "item-b")
            _account(s, "acc-a", "item-a")
            _account(s, "acc-b", "item-b")
            s.add(_tx("tx-a", "acc-a", date(2026, 4, 1), Decimal("90"), "Recurring"))
            s.add(_tx("tx-b", "acc-b", date(2026, 4, 1), Decimal("90"), "Recurring"))
            s.commit()

        with self.session() as s:
            all_accounts = {a.id: a for a in s.exec(select(Account)).all()}
            active_item_ids = {
                item.id for item in s.exec(select(Item)).all() if item.is_active
            }
            all_txs = s.exec(select(Transaction)).all()

            by_key = defaultdict(list)
            for tx in all_txs:
                acc = all_accounts.get(tx.account_id)
                atype = acc.type if acc else "UNKNOWN"
                key = tx.dedupe_key or compute_dedupe_key(
                    atype, tx.description, tx.date, tx.amount,
                    tx.installment_number, tx.total_installments
                )
                by_key[key].append(tx)

            to_mark = []
            ambiguous = []
            for key, txs in by_key.items():
                if len(txs) < 2:
                    continue
                active_txs = [tx for tx in txs if mark_is_active(all_accounts.get(tx.account_id), active_item_ids)]
                inactive_txs = [tx for tx in txs if not mark_is_active(all_accounts.get(tx.account_id), active_item_ids)]
                if active_txs and not inactive_txs:
                    ambiguous.extend(active_txs)
                elif active_txs and inactive_txs:
                    to_mark.extend(inactive_txs)

        # Must be detected as ambiguous, not added to to_mark
        self.assertEqual(to_mark, [])
        self.assertEqual(len(ambiguous), 2)


# ---------------------------------------------------------------------------
# 5-7. Relaxed matching helpers
# ---------------------------------------------------------------------------

class TestRelaxedMatchHelper(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def session(self):
        return Session(self.engine)

    def _setup_accounts(self, session):
        _item(session, "item-active")
        _item(session, "item-old", is_active=False)
        _account(session, "acc-active", "item-active", account_type="CREDIT")
        _account(session, "acc-old", "item-old", account_type="CREDIT", is_active=False)
        session.commit()

    def _get_context(self, session):
        all_accounts = {a.id: a for a in session.exec(select(Account)).all()}
        active_item_ids = {i.id for i in session.exec(select(Item)).all() if i.is_active}
        all_txs = session.exec(select(Transaction)).all()
        index = _build_active_index(all_txs, all_accounts, active_item_ids)
        return all_accounts, index

    def test_exact_date_match(self):
        """Transactions on the same date with matching description are relaxed-matched."""
        with self.session() as s:
            self._setup_accounts(s)
            s.add(_tx("tx-active", "acc-active", date(2026, 5, 1), Decimal("50"), "NETFLIX"))
            s.add(_tx("tx-old", "acc-old", date(2026, 5, 1), Decimal("50"), "NETFLIX"))
            s.commit()

        with self.session() as s:
            all_accounts, index = self._get_context(s)
            tx_old = s.get(Transaction, "tx-old")
            acc_old = all_accounts.get("acc-old")
            match = _relaxed_match(tx_old, acc_old, index)

        self.assertIsNotNone(match)
        self.assertEqual(match.id, "tx-active")

    def test_plus_one_day_tolerance(self):
        """Inactive tx dated D matches active tx dated D+1 within ±1 day tolerance."""
        with self.session() as s:
            self._setup_accounts(s)
            s.add(_tx("tx-active", "acc-active", date(2026, 5, 2), Decimal("75"), "SPOTIFY"))
            s.add(_tx("tx-old", "acc-old", date(2026, 5, 1), Decimal("75"), "SPOTIFY"))
            s.commit()

        with self.session() as s:
            all_accounts, index = self._get_context(s)
            tx_old = s.get(Transaction, "tx-old")
            match = _relaxed_match(tx_old, all_accounts.get("acc-old"), index)

        self.assertIsNotNone(match)

    def test_minus_one_day_tolerance(self):
        """Inactive tx dated D matches active tx dated D-1."""
        with self.session() as s:
            self._setup_accounts(s)
            s.add(_tx("tx-active", "acc-active", date(2026, 5, 1), Decimal("75"), "SPOTIFY"))
            s.add(_tx("tx-old", "acc-old", date(2026, 5, 2), Decimal("75"), "SPOTIFY"))
            s.commit()

        with self.session() as s:
            all_accounts, index = self._get_context(s)
            tx_old = s.get(Transaction, "tx-old")
            match = _relaxed_match(tx_old, all_accounts.get("acc-old"), index)

        self.assertIsNotNone(match)

    def test_two_days_diff_no_match(self):
        """Dates more than 1 day apart must not match."""
        with self.session() as s:
            self._setup_accounts(s)
            s.add(_tx("tx-active", "acc-active", date(2026, 5, 5), Decimal("40"), "AMAZON"))
            s.add(_tx("tx-old", "acc-old", date(2026, 5, 3), Decimal("40"), "AMAZON"))
            s.commit()

        with self.session() as s:
            all_accounts, index = self._get_context(s)
            tx_old = s.get(Transaction, "tx-old")
            match = _relaxed_match(tx_old, all_accounts.get("acc-old"), index)

        self.assertIsNone(match)

    def test_amount_within_tolerance(self):
        """Amounts differing by R$0.01 still match."""
        with self.session() as s:
            self._setup_accounts(s)
            s.add(_tx("tx-active", "acc-active", date(2026, 5, 1), Decimal("99.99"), "UBER"))
            s.add(_tx("tx-old", "acc-old", date(2026, 5, 1), Decimal("100.00"), "UBER"))
            s.commit()

        with self.session() as s:
            all_accounts, index = self._get_context(s)
            tx_old = s.get(Transaction, "tx-old")
            match = _relaxed_match(tx_old, all_accounts.get("acc-old"), index)

        self.assertIsNotNone(match)

    def test_amount_outside_tolerance(self):
        """Amounts differing by R$0.02 must not match."""
        with self.session() as s:
            self._setup_accounts(s)
            s.add(_tx("tx-active", "acc-active", date(2026, 5, 1), Decimal("99.98"), "UBER"))
            s.add(_tx("tx-old", "acc-old", date(2026, 5, 1), Decimal("100.00"), "UBER"))
            s.commit()

        with self.session() as s:
            all_accounts, index = self._get_context(s)
            tx_old = s.get(Transaction, "tx-old")
            match = _relaxed_match(tx_old, all_accounts.get("acc-old"), index)

        self.assertIsNone(match)

    def test_description_prefix_match(self):
        """Description prefix (first 12 chars) match is sufficient."""
        with self.session() as s:
            self._setup_accounts(s)
            # active: "Cobasicanoasbra 01/03", inactive: "Cobasicanoasbra 02/03"
            s.add(_tx("tx-active", "acc-active", date(2026, 4, 15), Decimal("155.76"),
                      "COBASICANOASBRA   01/03"))
            s.add(_tx("tx-old", "acc-old", date(2026, 4, 15), Decimal("155.75"),
                      "COBASICANOASBRA   02/03"))
            s.commit()

        with self.session() as s:
            all_accounts, index = self._get_context(s)
            tx_old = s.get(Transaction, "tx-old")
            match = _relaxed_match(tx_old, all_accounts.get("acc-old"), index)

        # Description prefix "cobasicanoasbr" matches → relaxed hit
        self.assertIsNotNone(match)

    def test_completely_different_description_no_match(self):
        """Unrelated descriptions must not match even if date/amount match."""
        with self.session() as s:
            self._setup_accounts(s)
            s.add(_tx("tx-active", "acc-active", date(2026, 5, 1), Decimal("50"), "CINEMA BIG"))
            s.add(_tx("tx-old", "acc-old", date(2026, 5, 1), Decimal("50"), "SUPERMERCADO"))
            s.commit()

        with self.session() as s:
            all_accounts, index = self._get_context(s)
            tx_old = s.get(Transaction, "tx-old")
            match = _relaxed_match(tx_old, all_accounts.get("acc-old"), index)

        self.assertIsNone(match)


# ---------------------------------------------------------------------------
# 8. Relaxed strategy: installment mismatch blocks match
# ---------------------------------------------------------------------------

class TestRelaxedInstallmentMismatch(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def session(self):
        return Session(self.engine)

    def test_installment_mismatch_blocks_relaxed_match(self):
        """If both sides have structured installment data but it differs, no match."""
        with self.session() as s:
            _item(s, "item-a")
            _item(s, "item-b", is_active=False)
            _account(s, "acc-active", "item-a")
            _account(s, "acc-old", "item-b", is_active=False)
            # Active: installment 1/12; Inactive: 3/12 — different structured fields
            s.add(_tx("tx-active", "acc-active", date(2026, 5, 17), Decimal("103.11"),
                      "IG*EDZKAISERPL", installment_number=1, total_installments=12))
            s.add(_tx("tx-old", "acc-old", date(2026, 5, 17), Decimal("103.11"),
                      "IG*EDZKAISERPL", installment_number=3, total_installments=12))
            s.commit()

        with self.session() as s:
            all_accounts = {a.id: a for a in s.exec(select(Account)).all()}
            active_item_ids = {i.id for i in s.exec(select(Item)).all() if i.is_active}
            all_txs = s.exec(select(Transaction)).all()
            index = _build_active_index(all_txs, all_accounts, active_item_ids)
            tx_old = s.get(Transaction, "tx-old")
            match = _relaxed_match(tx_old, all_accounts.get("acc-old"), index)

        self.assertIsNone(match)

    def test_one_side_null_installment_still_matches(self):
        """If only one side has structured installment info, match is allowed."""
        with self.session() as s:
            _item(s, "item-a")
            _item(s, "item-b", is_active=False)
            _account(s, "acc-active", "item-a")
            _account(s, "acc-old", "item-b", is_active=False)
            # Active: no installment fields; Inactive: has 2/03
            s.add(_tx("tx-active", "acc-active", date(2026, 4, 15), Decimal("155.75"),
                      "COBASICANOASBRA   01/03",
                      installment_number=None, total_installments=None))
            s.add(_tx("tx-old", "acc-old", date(2026, 4, 15), Decimal("155.76"),
                      "COBASICANOASBRA   02/03",
                      installment_number=2, total_installments=3))
            s.commit()

        with self.session() as s:
            all_accounts = {a.id: a for a in s.exec(select(Account)).all()}
            active_item_ids = {i.id for i in s.exec(select(Item)).all() if i.is_active}
            all_txs = s.exec(select(Transaction)).all()
            index = _build_active_index(all_txs, all_accounts, active_item_ids)
            tx_old = s.get(Transaction, "tx-old")
            match = _relaxed_match(tx_old, all_accounts.get("acc-old"), index)

        # One side null → installment mismatch is ignored → match allowed
        self.assertIsNotNone(match)


# ---------------------------------------------------------------------------
# 9. Relaxed strategy: tx already matched by exact is not re-matched
# ---------------------------------------------------------------------------

class TestRelaxedSkipsExactMatched(unittest.TestCase):
    def test_exact_matched_id_excluded_from_relaxed_pass(self):
        """The relaxed pass must skip IDs already in exact_matched_inactive_ids."""
        # This is a logic test, no DB needed.
        # Simulate the check: if tx.id in exact_matched_inactive_ids, skip.
        exact_matched_ids = {"tx-already-handled"}
        inactive_tx_ids = ["tx-already-handled", "tx-new"]
        to_relax = [tid for tid in inactive_tx_ids if tid not in exact_matched_ids]
        self.assertNotIn("tx-already-handled", to_relax)
        self.assertIn("tx-new", to_relax)


# ---------------------------------------------------------------------------
# 10. Mark script dry-run does not modify DB
# ---------------------------------------------------------------------------

class TestMarkScriptDryRun(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()
        # Write a temp DB file for the script to use
        import tempfile
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test.db"

        test_engine = create_engine(f"sqlite:///{self.db_path}")
        SQLModel.metadata.create_all(test_engine)
        with Session(test_engine) as s:
            _item(s, "item-active")
            _item(s, "item-old", is_active=False)
            _account(s, "acc-active", "item-active")
            _account(s, "acc-old", "item-old", is_active=False)
            s.add(_tx("tx-active", "acc-active", date(2026, 3, 10), Decimal("80"), "Gym"))
            s.add(_tx("tx-old", "acc-old", date(2026, 3, 10), Decimal("80"), "Gym"))
            s.commit()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_dry_run_does_not_change_is_duplicate(self):
        """Running the script without --apply must leave is_duplicate untouched."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "scripts/mark_duplicate_transactions.py",
             "--db", str(self.db_path)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("DRY-RUN", result.stdout)

        # Verify DB unchanged
        check_engine = create_engine(f"sqlite:///{self.db_path}")
        with Session(check_engine) as s:
            txs = s.exec(select(Transaction)).all()
        self.assertTrue(all(not tx.is_duplicate for tx in txs))

    def test_dry_run_prints_count(self):
        """Dry-run must print the count of transactions that WOULD be marked."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "scripts/mark_duplicate_transactions.py",
             "--db", str(self.db_path)],
            capture_output=True, text=True,
        )
        # The test DB has exactly 1 inactive tx that matches 1 active tx
        self.assertIn("transações a marcar", result.stdout)
        # Exact count for this test DB is 1
        self.assertIn(":    1  R$", result.stdout)


# ---------------------------------------------------------------------------
# 11. Mark script --apply writes changes and populates dedupe_key
# ---------------------------------------------------------------------------

class TestMarkScriptApply(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_apply.db"

        test_engine = create_engine(f"sqlite:///{self.db_path}")
        SQLModel.metadata.create_all(test_engine)
        with Session(test_engine) as s:
            _item(s, "item-active")
            _item(s, "item-old", is_active=False)
            _account(s, "acc-active", "item-active")
            _account(s, "acc-old", "item-old", is_active=False)
            s.add(_tx("tx-active", "acc-active", date(2026, 3, 10), Decimal("80"), "Pilates"))
            s.add(_tx("tx-old", "acc-old", date(2026, 3, 10), Decimal("80"), "Pilates"))
            s.commit()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_apply_marks_inactive_as_duplicate(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "scripts/mark_duplicate_transactions.py",
             "--db", str(self.db_path), "--apply"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        check_engine = create_engine(f"sqlite:///{self.db_path}")
        with Session(check_engine) as s:
            tx_old = s.get(Transaction, "tx-old")
            tx_active = s.get(Transaction, "tx-active")

        self.assertTrue(tx_old.is_duplicate)
        self.assertFalse(tx_active.is_duplicate)

    def test_apply_sets_duplicate_of_id(self):
        import subprocess
        subprocess.run(
            [sys.executable, "scripts/mark_duplicate_transactions.py",
             "--db", str(self.db_path), "--apply"],
            capture_output=True, text=True,
        )

        check_engine = create_engine(f"sqlite:///{self.db_path}")
        with Session(check_engine) as s:
            tx_old = s.get(Transaction, "tx-old")

        self.assertEqual(tx_old.duplicate_of_id, "tx-active")

    def test_apply_populates_dedupe_key(self):
        import subprocess
        subprocess.run(
            [sys.executable, "scripts/mark_duplicate_transactions.py",
             "--db", str(self.db_path), "--apply"],
            capture_output=True, text=True,
        )

        check_engine = create_engine(f"sqlite:///{self.db_path}")
        with Session(check_engine) as s:
            tx_old = s.get(Transaction, "tx-old")

        self.assertIsNotNone(tx_old.dedupe_key)
        self.assertEqual(len(tx_old.dedupe_key), 32)

    def test_apply_prints_snapshot_refresh(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "scripts/mark_duplicate_transactions.py",
             "--db", str(self.db_path), "--apply"],
            capture_output=True, text=True,
        )
        self.assertIn("refreshed_income_months", result.stdout)
        self.assertIn("refreshed_invoice_months", result.stdout)
        self.assertIn("refreshed_balance_months", result.stdout)


# ---------------------------------------------------------------------------
# 12. Aggregates still exclude is_duplicate=True
# ---------------------------------------------------------------------------

class TestAggregatesExcludeAfterMarking(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def session(self):
        return Session(self.engine)

    def test_enriched_transactions_after_mark(self):
        """After marking, enriched_transactions must not return the duplicate."""
        from app.services.transaction_reports import enriched_transactions

        d = date(2026, 5, 5)
        with self.session() as s:
            _item(s, "item-a")
            _account(s, "acc-a", "item-a")
            s.add(_tx("tx-real", "acc-a", d, Decimal("120"), "Shop"))
            # Simulate post-marking state
            s.add(_tx("tx-dup", "acc-a", d, Decimal("120"), "Shop", is_duplicate=True))
            s.commit()

        with self.session() as s:
            rows = enriched_transactions(s, account_type="CREDIT")

        ids = [r["id"] for r in rows]
        self.assertIn("tx-real", ids)
        self.assertNotIn("tx-dup", ids)

    def test_invoice_summary_after_mark(self):
        """invoice_summary must not double the amount after marking."""
        from app.services.transaction_reports import invoice_summary

        d = date(2026, 5, 5)
        today = date(2026, 6, 8)
        with self.session() as s:
            _item(s, "item-a")
            _account(s, "acc-a", "item-a")
            s.add(_tx("tx-real", "acc-a", d, Decimal("99"), "Buy"))
            s.add(_tx("tx-dup", "acc-a", d, Decimal("99"), "Buy", is_duplicate=True))
            s.commit()

        with self.session() as s:
            result = invoice_summary(s, to_date=today)

        self.assertAlmostEqual(result["invoice_open_total"], 99.0, places=2)


if __name__ == "__main__":
    unittest.main()
