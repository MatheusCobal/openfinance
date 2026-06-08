#!/usr/bin/env python3
"""Mark duplicate transactions after Pluggy re-authentication.

Dry-run by default — pass --apply to write changes to the database.
No transactions are ever deleted.

Strategies
----------
EXACT (always applied with --apply):
  Group all transactions by their dedupe_key
  (account_type + normalized_description + date + |amount| + installments).
  For each group that has BOTH active AND inactive copies, mark the inactive
  copies as is_duplicate=True and point duplicate_of_id → active canonical.
  Groups that are all-active or all-inactive are skipped automatically.

RELAXED (opt-in with --include-relaxed):
  For inactive transactions NOT matched by the exact strategy, look for active
  transactions within ±1 day, ±R$0.01, and the same description prefix.
  Installments must match when both sides supply them.
  These matches are lower confidence and reported separately.
  Active-vs-active conflicts are never auto-marked regardless of strategy.

Usage:
    python scripts/mark_duplicate_transactions.py [--db PATH] [--apply]
                                                   [--include-relaxed]

Options:
    --db PATH           Path to the SQLite database (default: openfinance.db)
    --apply             Write changes to the database (default: dry-run)
    --include-relaxed   Also mark relaxed-match duplicates (lower confidence)
"""
import argparse
import sys
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, create_engine, select

from app.categorization import normalize_description
from app.models import Account, Item, Transaction
from app.services.sync import compute_dedupe_key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_active(account: Optional[Account], active_item_ids: set) -> bool:
    if account is None:
        return False
    return bool(account.is_active and account.item_id in active_item_ids)


def _desc_prefix(description: Optional[str], length: int = 12) -> str:
    return normalize_description(description)[:length]


def _build_active_index(
    all_txs: List[Transaction],
    all_accounts: Dict[str, Account],
    active_item_ids: set,
) -> Dict[Tuple, List[Transaction]]:
    """Index of active transactions by (account_type, date) for relaxed lookup."""
    index: Dict[Tuple, List[Transaction]] = defaultdict(list)
    for tx in all_txs:
        if not _is_active(all_accounts.get(tx.account_id), active_item_ids):
            continue
        account = all_accounts.get(tx.account_id)
        if account:
            index[(account.type, tx.date)].append(tx)
    return index


def _relaxed_match(
    inactive_tx: Transaction,
    inactive_account: Optional[Account],
    active_index: Dict[Tuple, List[Transaction]],
    amount_tolerance: Decimal = Decimal("0.01"),
    day_tolerance: int = 1,
    desc_prefix_len: int = 12,
) -> Optional[Transaction]:
    """Return the best active match for an inactive transaction, or None."""
    if inactive_account is None:
        return None
    account_type = inactive_account.type
    desc_pfx = _desc_prefix(inactive_tx.description, desc_prefix_len)
    abs_amount = abs(inactive_tx.amount)
    inst_key = (
        inactive_tx.installment_number or 0,
        inactive_tx.total_installments or 0,
    )

    for delta in range(-day_tolerance, day_tolerance + 1):
        search_date = inactive_tx.date + timedelta(days=delta)
        for candidate in active_index.get((account_type, search_date), []):
            if abs(abs(candidate.amount) - abs_amount) > amount_tolerance:
                continue
            cand_pfx = _desc_prefix(candidate.description, desc_prefix_len)
            if not desc_pfx or not cand_pfx or cand_pfx != desc_pfx:
                continue
            cand_inst = (candidate.installment_number or 0, candidate.total_installments or 0)
            if inst_key != (0, 0) and cand_inst != (0, 0) and inst_key != cand_inst:
                continue
            return candidate  # return first match; all are equivalent for our purposes
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", default="openfinance.db", help="Path to the SQLite database")
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write changes to the database (default: dry-run)",
    )
    parser.add_argument(
        "--include-relaxed",
        action="store_true",
        default=False,
        dest="include_relaxed",
        help="Also mark relaxed-match duplicates (lower confidence)",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print("=" * 70)
    print(f"MARCAR TRANSAÇÕES DUPLICADAS ({mode})")
    print("=" * 70)
    print(f"Database: {db_path}")
    if not args.apply:
        print("(Sem --apply: nenhuma alteração será gravada)")
    if args.include_relaxed:
        print("(--include-relaxed: matching relaxado também será aplicado)")
    print()

    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )

    with Session(engine) as session:
        all_accounts: Dict[str, Account] = {
            a.id: a for a in session.exec(select(Account)).all()
        }
        active_item_ids = {
            item.id for item in session.exec(select(Item)).all() if item.is_active
        }

        def is_active(account_id: str) -> bool:
            return _is_active(all_accounts.get(account_id), active_item_ids)

        all_txs = session.exec(select(Transaction)).all()

        # -------------------------------------------------------------------
        # Strategy 1: EXACT key matching
        # -------------------------------------------------------------------
        by_key: Dict[str, List[Transaction]] = defaultdict(list)
        for tx in all_txs:
            account = all_accounts.get(tx.account_id)
            account_type = account.type if account else "UNKNOWN"
            key = tx.dedupe_key or compute_dedupe_key(
                account_type, tx.description, tx.date,
                tx.amount, tx.installment_number, tx.total_installments,
            )
            by_key[key].append(tx)

        # to_mark_exact: list of (tx_to_mark, canonical_id)
        to_mark_exact: List[Tuple[Transaction, str]] = []
        ambiguous_groups: List[List[Transaction]] = []

        exact_matched_inactive_ids: set = set()

        for key, txs in by_key.items():
            if len(txs) < 2:
                continue
            active_txs = [tx for tx in txs if is_active(tx.account_id)]
            inactive_txs = [tx for tx in txs if not is_active(tx.account_id)]

            # All-active duplicate: suspicious but never auto-mark.
            if active_txs and not inactive_txs:
                ambiguous_groups.append(active_txs)
                continue

            # No active counterpart: cannot determine canonical, skip.
            if not active_txs:
                continue

            # Has both active and inactive: mark inactive ones.
            canonical_id = active_txs[0].id
            for tx in inactive_txs:
                if not tx.is_duplicate:
                    to_mark_exact.append((tx, canonical_id))
                    exact_matched_inactive_ids.add(tx.id)

        # -------------------------------------------------------------------
        # Strategy 2: RELAXED matching
        # -------------------------------------------------------------------
        to_mark_relaxed: List[Tuple[Transaction, str]] = []

        if args.include_relaxed:
            active_index = _build_active_index(all_txs, all_accounts, active_item_ids)
            for tx in all_txs:
                if is_active(tx.account_id):
                    continue
                if tx.id in exact_matched_inactive_ids:
                    continue  # already covered
                if tx.is_duplicate:
                    continue  # already marked
                account = all_accounts.get(tx.account_id)
                best_match = _relaxed_match(tx, account, active_index)
                if best_match is not None:
                    to_mark_relaxed.append((tx, best_match.id))

        # -------------------------------------------------------------------
        # Report
        # -------------------------------------------------------------------
        all_to_mark = to_mark_exact + to_mark_relaxed
        exact_amount = sum(abs(Decimal(str(tx.amount))) for tx, _ in to_mark_exact)
        relaxed_amount = sum(abs(Decimal(str(tx.amount))) for tx, _ in to_mark_relaxed)

        print(f"Estratégia EXATA   — transações a marcar: {len(to_mark_exact):4d}  R$ {exact_amount:>12,.2f}")
        print(f"Estratégia RELAXADA— transações a marcar: {len(to_mark_relaxed):4d}  R$ {relaxed_amount:>12,.2f}")
        print(f"Grupos ambíguos (só-ativo, não tocados):  {len(ambiguous_groups):4d}")
        print()

        if to_mark_exact:
            print(f"Detalhes EXATO (primeiros 30):")
            print("-" * 70)
            for tx, canonical_id in sorted(
                to_mark_exact, key=lambda x: (x[0].date, x[0].description or "")
            )[:30]:
                print(
                    f"  {tx.date}  R${abs(float(tx.amount)):>10.2f}  "
                    f"{(tx.description or '')[:40]:40s}  "
                    f"acc={tx.account_id[:8]}...  → {canonical_id[:8]}..."
                )
            if len(to_mark_exact) > 30:
                print(f"  ... e mais {len(to_mark_exact) - 30} transações")
            print()

        if to_mark_relaxed:
            print(f"Detalhes RELAXADO (primeiros 15):")
            print("-" * 70)
            for tx, canonical_id in to_mark_relaxed[:15]:
                print(
                    f"  {tx.date}  R${abs(float(tx.amount)):>10.2f}  "
                    f"{(tx.description or '')[:40]:40s}  "
                    f"acc={tx.account_id[:8]}...  → {canonical_id[:8]}..."
                )
            if len(to_mark_relaxed) > 15:
                print(f"  ... e mais {len(to_mark_relaxed) - 15} transações")
            print()

        if not all_to_mark:
            print("Nenhuma duplicata para marcar. Nada a fazer.")
            return

        if not args.apply:
            print(
                "DRY-RUN: nenhuma alteração gravada. "
                "Use --apply para confirmar."
            )
            return

        # -------------------------------------------------------------------
        # Apply
        # -------------------------------------------------------------------
        print("Aplicando alterações...")
        marked_exact = 0
        marked_relaxed = 0

        def _mark(tx: Transaction, canonical_id: str, strategy: str) -> None:
            nonlocal marked_exact, marked_relaxed
            tx.is_duplicate = True
            tx.duplicate_of_id = canonical_id
            # Populate dedupe_key if missing so future runs are faster
            if tx.dedupe_key is None:
                account = all_accounts.get(tx.account_id)
                account_type = account.type if account else "UNKNOWN"
                tx.dedupe_key = compute_dedupe_key(
                    account_type, tx.description, tx.date,
                    tx.amount, tx.installment_number, tx.total_installments,
                )
            session.add(tx)
            if strategy == "exact":
                marked_exact += 1
            else:
                marked_relaxed += 1

        batch = 0
        for tx, canonical_id in all_to_mark:
            _mark(tx, canonical_id, "exact" if tx in [t for t, _ in to_mark_exact] else "relaxed")
            batch += 1
            if batch % 200 == 0:
                session.commit()
                print(f"  {batch}/{len(all_to_mark)} marcadas...")

        session.commit()

        # More accurate counts using index
        exact_ids = {tx.id for tx, _ in to_mark_exact}
        relaxed_ids = {tx.id for tx, _ in to_mark_relaxed}
        marked_exact_final = sum(1 for tx, _ in to_mark_exact)
        marked_relaxed_final = sum(1 for tx, _ in to_mark_relaxed)

        print(f"Concluído:")
        print(f"  Marcadas por estratégia EXATA:    {marked_exact_final}")
        print(f"  Marcadas por estratégia RELAXADA: {marked_relaxed_final}")
        print(f"  Total:                            {marked_exact_final + marked_relaxed_final}")
        print()

        # -------------------------------------------------------------------
        # Refresh monthly snapshots
        # -------------------------------------------------------------------
        print("Recalculando snapshots mensais...")
        from app.services.snapshots import refresh_monthly_balance_snapshots
        refreshed_income, refreshed_invoice, refreshed_balance = (
            refresh_monthly_balance_snapshots(session)
        )
        print(f"  refreshed_income_months:  {refreshed_income}")
        print(f"  refreshed_invoice_months: {refreshed_invoice}")
        print(f"  refreshed_balance_months: {refreshed_balance}")
        print()
        print(
            "NOTA: as transações originais NÃO foram deletadas.\n"
            "Para removê-las fisicamente (somente após verificação):\n"
            "  sqlite3 openfinance.db \"DELETE FROM 'transaction' WHERE is_duplicate=1\""
        )


if __name__ == "__main__":
    main()
